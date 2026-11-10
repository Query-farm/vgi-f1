"""Tests for the Jolpica-F1 and OpenF1 HTTP boundary."""

from __future__ import annotations

import httpx
import pytest
from fixture_routes import load

from vgi_f1 import __version__, api


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(api.time, "sleep", slept.append)
    for limiter in (api._JOLPICA_LIMITER, api._OPENF1_LIMITER):
        monkeypatch.setattr(limiter, "acquire", lambda deadline: None)
    return slept


def test_user_agent_is_honest_and_versioned() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=load("jolpica_seasons.json"))

    with _client(handler) as client:
        api.fetch_jolpica("seasons", "Seasons", client=client)

    assert seen[0].headers["User-Agent"] == f"vgi-f1/{__version__} (+https://github.com/Query-farm/vgi-f1)"
    assert seen[0].url.path == "/ergast/f1/seasons.json"
    assert seen[0].url.params["limit"] == "100"
    assert seen[0].url.params["offset"] == "0"


def test_owned_client_follows_redirects() -> None:
    client = api._client(None)
    try:
        assert client.follow_redirects is True
    finally:
        client.close()


def test_base_urls_are_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("F1_JOLPICA_BASE_URL", "http://127.0.0.1:9/jolpica/")
    monkeypatch.setenv("F1_OPENF1_BASE_URL", "http://127.0.0.1:9/openf1/")
    assert api.jolpica_base_url() == "http://127.0.0.1:9/jolpica"
    assert api.openf1_base_url() == "http://127.0.0.1:9/openf1"
    monkeypatch.delenv("F1_JOLPICA_BASE_URL")
    monkeypatch.delenv("F1_OPENF1_BASE_URL")
    assert api.jolpica_base_url() == api.DEFAULT_JOLPICA_BASE_URL
    assert api.openf1_base_url() == api.DEFAULT_OPENF1_BASE_URL


def test_jolpica_follows_every_page_and_joins_split_races() -> None:
    """Jolpica pages by result row, so one race's results can span two pages."""
    payload = load("jolpica_2024_results.json")
    races = payload["MRData"]["RaceTable"]["Races"]
    first = {**races[0], "Results": races[0]["Results"][:2]}
    second = {**races[0], "Results": races[0]["Results"][2:]}
    pages = [[first], [second, races[1]]]
    offsets: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offsets.append(request.url.params["offset"])
        index = len(offsets) - 1
        body = {
            "MRData": {
                "limit": "2",
                "offset": str(index * 2),
                "total": "6",
                "RaceTable": {"season": "2024", "Races": pages[index] if index < 2 else []},
            }
        }
        return httpx.Response(200, json=body)

    with _client(handler) as client:
        result = api.fetch_jolpica("2024/results", "Races", client=client)

    assert offsets == ["0", "2", "4"]
    assert [race["round"] for race in result.items] == ["1", "2"]
    assert len(result.items[0]["Results"]) == 3
    assert result.context == {"season": "2024"}


def test_lap_entries_split_across_pages_are_merged() -> None:
    payload = load("jolpica_2024_5_laps.json")
    race = payload["MRData"]["RaceTable"]["Races"][0]
    lap = race["Laps"][0]
    pages = [
        {**race, "Laps": [{"number": lap["number"], "Timings": lap["Timings"][:1]}]},
        {**race, "Laps": [{"number": lap["number"], "Timings": lap["Timings"][1:]}, race["Laps"][1]]},
    ]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = {"MRData": {"limit": "3", "total": "6", "RaceTable": {"Races": [pages[calls - 1]]}}}
        return httpx.Response(200, json=body)

    with _client(handler) as client:
        result = api.fetch_jolpica("2024/5/laps", "Races", client=client)

    laps = result.items[0]["Laps"]
    assert [entry["number"] for entry in laps] == ["1", "2"]
    assert len(laps[0]["Timings"]) == 3


def test_pagination_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "JOLPICA_MAX_PAGES", 2)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, json={"MRData": {"limit": "100", "total": "9999", "DriverTable": {"Drivers": []}}}
        )

    with _client(handler) as client, pytest.raises(RuntimeError, match="exceeded 2 pages"):
        api.fetch_jolpica("drivers", "Drivers", client=client)
    assert calls == 2


def test_single_page_reports_the_next_offset() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        body = {"MRData": {"limit": "100", "total": "150", "DriverTable": {"Drivers": [{"driverId": "x"}]}}}
        return httpx.Response(200, json={**body, "offset": offset})

    with _client(handler) as client:
        first = api.fetch_jolpica_page("drivers", "Drivers", client=client)
        last = api.fetch_jolpica_page("drivers", "Drivers", offset=100, client=client)
    assert first.next_offset == 100
    assert last.next_offset is None
    assert last.items == [{"driverId": "x"}]


def test_unknown_list_and_malformed_payload_are_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported Jolpica list"):
        api.fetch_jolpica("seasons", "Bogus")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"MRData": {"total": "0"}})

    with _client(handler) as client, pytest.raises(ValueError, match="has no SeasonTable"):
        api.fetch_jolpica("seasons", "Seasons", client=client)


def test_non_json_success_is_rejected() -> None:
    with (
        _client(lambda request: httpx.Response(200, text="<html>")) as client,
        pytest.raises(ValueError, match="non-JSON"),
    ):
        api.fetch_jolpica("seasons", "Seasons", client=client)


def test_cache_serves_repeat_requests_without_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, json=load("jolpica_seasons.json"), headers={"Cache-Control": "max-age=600"}
        )

    with _client(handler) as client:
        first = api.fetch_jolpica("seasons", "Seasons", client=client)
        second = api.fetch_jolpica("seasons", "Seasons", client=client)

    assert calls == 1
    assert first.items == second.items
    assert first.ttl == api.CURRENT_TTL
    assert 0 < second.ttl <= api.CURRENT_TTL


def test_historical_requests_use_long_ttl_and_origin_max_age_can_extend_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=load("jolpica_seasons.json"), headers={"Cache-Control": "max-age=90000"}
        )

    with _client(handler) as client:
        result = api.fetch_jolpica("seasons", "Seasons", historical=True, client=client)
    assert result.ttl == 90_000
    assert api.is_historical(2024)
    assert not api.is_historical(None)
    assert not api.is_historical(9999)


def test_cache_is_bounded_and_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = api._ResponseCache(max_entries=2)
    for key in ("a", "b", "c"):
        cache.store(key, api.ApiResponse(payload=key, ttl=60))
    assert cache.get("a") is None
    assert cache.get("c").payload == "c"
    cache.store("zero", api.ApiResponse(payload=1, ttl=0))
    assert cache.get("zero") is None

    clock = [1_000.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    cache.store("soon", api.ApiResponse(payload=1, ttl=10))
    clock[0] += 11
    assert cache.get("soon") is None


def test_retries_429_honoring_retry_after(no_sleep: list[float]) -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "2"}, text="slow down"),
            httpx.Response(503, text="busy"),
            httpx.Response(200, json=load("jolpica_seasons.json")),
        ]
    )
    with _client(lambda request: next(responses)) as client:
        result = api.fetch_jolpica("seasons", "Seasons", client=client)
    assert len(result.items) == 3
    assert no_sleep[0] == 2.0
    assert 0.5 <= no_sleep[1] <= 30


def test_retry_after_http_date_and_garbage() -> None:
    dated = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert 0.5 <= api._retry_delay(dated, 0) <= 0.625  # a past date falls back to backoff
    garbage = httpx.Response(429, headers={"Retry-After": "soon"})
    assert 0.5 <= api._retry_delay(garbage, 0) <= 0.625
    assert api._retry_delay(httpx.Response(429, headers={"Retry-After": "3600"}), 0) == api.MAX_RETRY_DELAY


def test_persistent_failure_is_descriptive(no_sleep: list[float]) -> None:
    with (
        _client(lambda request: httpx.Response(500, text="boom")) as client,
        pytest.raises(api.F1ApiError, match="Jolpica-F1 returned HTTP 500: boom"),
    ):
        api.fetch_jolpica("seasons", "Seasons", client=client)
    assert len(no_sleep) == api.MAX_ATTEMPTS - 1


def test_client_errors_are_not_retried(no_sleep: list[float]) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="Bad Request: season")

    with _client(handler) as client, pytest.raises(api.F1ApiError) as caught:
        api.fetch_jolpica("1800/results", "Races", client=client)
    assert calls == 1
    assert caught.value.status == 400
    assert no_sleep == []


def test_transport_errors_are_retried_then_raised(no_sleep: list[float]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with _client(handler) as client, pytest.raises(httpx.ConnectError):
        api.fetch_openf1("sessions", {"year": 2024}, client=client)
    assert len(no_sleep) == api.MAX_ATTEMPTS - 1


def test_openf1_not_found_means_empty() -> None:
    with _client(lambda request: httpx.Response(404, json=load("openf1_not_found.json"))) as client:
        result = api.fetch_openf1("starting_grid", {"session_key": 9472}, client=client)
    assert result.payload == []


def test_openf1_too_much_data_is_reported() -> None:
    body = {"detail": "Failed to retrieve information. You're likely asking for too much data at once."}
    with (
        _client(lambda request: httpx.Response(422, json=body)) as client,
        pytest.raises(api.F1ApiError, match="OpenF1 returned HTTP 422"),
    ):
        api.fetch_openf1("location", {"session_key": 9472}, client=client)


def test_openf1_requires_array_payload() -> None:
    with (
        _client(lambda request: httpx.Response(200, json={"detail": "x"})) as client,
        pytest.raises(ValueError, match="not a JSON array"),
    ):
        api.fetch_openf1("sessions", {"year": 2024}, client=client)


def test_openf1_query_and_ttl() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=load("openf1_stints_9472.json"))

    with _client(handler) as client:
        result = api.fetch_openf1("stints", {"session_key": 9472}, ttl=123, client=client)
    assert seen[0].url.path == "/v1/stints"
    assert seen[0].url.params["session_key"] == "9472"
    assert result.ttl == 123
    assert len(result.payload) == 3


def test_rate_limiter_waits_within_window(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api.time, "sleep", sleep)
    limiter = api._RateLimiter("Test", ((2, 1.0), (3, 60.0)))
    limiter.acquire(deadline=1_000)
    limiter.acquire(deadline=1_000)
    limiter.acquire(deadline=1_000)
    assert slept == [pytest.approx(1.0)]
    with pytest.raises(api.RateLimitExceeded, match="Test rate limit reached"):
        limiter.acquire(deadline=clock[0] + 5)


def test_query_deadline_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "QUERY_TIMEOUT", -1.0)
    with (
        _client(lambda request: httpx.Response(200, json=[])) as client,
        pytest.raises(TimeoutError, match="exceeded"),
    ):
        api.fetch_openf1("sessions", {"year": 2024}, client=client)


def test_fixture_transport_serves_both_sources(fixture_transport: list[httpx.Request]) -> None:
    standings = api.fetch_jolpica("current/driverStandings", "StandingsLists")
    sessions = api.fetch_openf1("sessions", {"year": 2024, "session_name": "Race"})
    assert standings.items[0]["season"] == "2026"
    assert sessions.payload[0]["session_key"] == 9472
    assert {request.url.host for request in fixture_transport} == {"jolpica.test", "openf1.test"}
