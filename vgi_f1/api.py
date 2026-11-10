"""Small, read-only clients for the Jolpica-F1 (Ergast-compatible) and OpenF1 APIs.

Every outbound request goes through :func:`_get`, which applies the source's
published rate limits, retries transient failures, honors ``Retry-After``, and
keeps a bounded in-process response cache so repeated SQL queries do not spend
the shared upstream budget twice.
"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from vgi_f1 import __version__

DEFAULT_JOLPICA_BASE_URL = "https://api.jolpi.ca/ergast/f1"
DEFAULT_OPENF1_BASE_URL = "https://api.openf1.org/v1"
USER_AGENT = f"vgi-f1/{__version__} (+https://github.com/Query-farm/vgi-f1)"

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
MAX_RETRY_DELAY = 30.0
QUERY_TIMEOUT = 120.0

# Jolpica allows a burst of 4 requests per second and 500 per hour; it pages
# at most 100 rows per request.
JOLPICA_PAGE_SIZE = 100
JOLPICA_MAX_PAGES = 30
JOLPICA_LIMITS = ((4, 1.0), (500, 3_600.0))
# OpenF1's keyless historical tier allows 30 requests per minute (3 per second).
OPENF1_LIMITS = ((3, 1.0), (30, 60.0))

# Cache lifetimes used when the origin does not supply a longer max-age.
CURRENT_TTL = 600
HISTORICAL_TTL = 6 * 3_600
CACHE_MAX_ENTRIES = 256

logger = logging.getLogger(__name__)

_MAX_AGE = re.compile(r"(?:^|[,\s])max-age=(\d+)", re.IGNORECASE)


class F1ApiError(RuntimeError):
    """A failed response from an upstream F1 data API."""

    def __init__(self, source: str, status: int, body: str) -> None:
        super().__init__(f"{source} returned HTTP {status}: {body[:400]}")
        self.source = source
        self.status = status


class RateLimitExceeded(RuntimeError):
    """The local budget for an upstream API is exhausted for the current window."""


@dataclass(frozen=True, slots=True)
class ApiResponse:
    """Decoded JSON payload plus the freshness lifetime to forward to VGI clients."""

    payload: Any
    ttl: int


class _RateLimiter:
    """Sliding-window limiter enforcing every ``(count, seconds)`` window at once."""

    def __init__(self, name: str, limits: tuple[tuple[int, float], ...]) -> None:
        self.name = name
        self.limits = limits
        self._history: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, deadline: float) -> None:
        """Block until a request is allowed, or raise if that would pass ``deadline``."""
        longest = max(seconds for _, seconds in self.limits)
        while True:
            with self._lock:
                now = time.monotonic()
                while self._history and now - self._history[0] >= longest:
                    self._history.popleft()
                wait = 0.0
                for count, seconds in self.limits:
                    recent = [stamp for stamp in self._history if now - stamp < seconds]
                    if len(recent) >= count:
                        wait = max(wait, recent[-count] + seconds - now)
                if wait <= 0:
                    self._history.append(now)
                    return
            if now + wait > deadline:
                raise RateLimitExceeded(
                    f"{self.name} rate limit reached; the next request is allowed in {wait:.0f} seconds. "
                    "Retry later or narrow the query."
                )
            time.sleep(wait)

    def reset(self) -> None:
        """Forget request history (used by tests)."""
        with self._lock:
            self._history.clear()


class _ResponseCache:
    """Bounded, thread-safe LRU cache of decoded JSON payloads with expiry."""

    def __init__(self, max_entries: int) -> None:
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, int, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> ApiResponse | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires, ttl, payload = entry
            remaining = expires - time.monotonic()
            if remaining <= 0:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return ApiResponse(payload=payload, ttl=min(ttl, max(1, int(remaining))))

    def store(self, key: str, response: ApiResponse) -> None:
        if response.ttl <= 0:
            return
        with self._lock:
            self._entries[key] = (time.monotonic() + response.ttl, response.ttl, response.payload)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_JOLPICA_LIMITER = _RateLimiter("Jolpica-F1", JOLPICA_LIMITS)
_OPENF1_LIMITER = _RateLimiter("OpenF1", OPENF1_LIMITS)
_CACHE = _ResponseCache(CACHE_MAX_ENTRIES)


def reset_state() -> None:
    """Clear the response cache and rate-limit history (used by tests)."""
    _CACHE.clear()
    _JOLPICA_LIMITER.reset()
    _OPENF1_LIMITER.reset()


def jolpica_base_url() -> str:
    """Return the Jolpica-F1 root, optionally overridden for hermetic tests."""
    return os.environ.get("F1_JOLPICA_BASE_URL", DEFAULT_JOLPICA_BASE_URL).rstrip("/")


def openf1_base_url() -> str:
    """Return the OpenF1 root, optionally overridden for hermetic tests."""
    return os.environ.get("F1_OPENF1_BASE_URL", DEFAULT_OPENF1_BASE_URL).rstrip("/")


def _max_age(response: httpx.Response) -> int | None:
    match = _MAX_AGE.search(response.headers.get("cache-control", ""))
    return int(match.group(1)) if match else None


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Return a bounded Retry-After delay or exponential backoff with jitter."""
    if response is not None:
        raw = response.headers.get("retry-after")
        if raw:
            try:
                delay = float(raw)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(raw)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    delay = (retry_at - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = -1.0
            if delay >= 0:
                return min(delay, MAX_RETRY_DELAY)
    base = min(0.5 * 2**attempt, MAX_RETRY_DELAY)
    return min(base + random.uniform(0, base * 0.25), MAX_RETRY_DELAY)


def _cache_key(url: str, params: Mapping[str, str | int]) -> str:
    query = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return f"{url}?{query}"


def _get(
    *,
    source: str,
    url: str,
    params: Mapping[str, str | int],
    limiter: _RateLimiter,
    ttl: int,
    deadline: float,
    client: httpx.Client,
    empty_on_404: bool = False,
) -> ApiResponse:
    """Issue one cached, rate-limited GET, retrying transient failures."""
    key = _cache_key(url, params)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    response: httpx.Response | None = None
    for attempt in range(MAX_ATTEMPTS):
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{source} query exceeded {QUERY_TIMEOUT:g} seconds")
        limiter.acquire(deadline)
        remaining = max(0.1, deadline - time.monotonic())
        started = time.monotonic()
        try:
            response = client.get(
                url,
                params=params,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                timeout=httpx.Timeout(min(30.0, remaining), connect=min(10.0, remaining)),
            )
        except httpx.TransportError:
            logger.warning("f1_api_transport_error source=%s url=%s attempt=%d", source, url, attempt + 1)
            if attempt + 1 == MAX_ATTEMPTS:
                raise
            time.sleep(min(_retry_delay(None, attempt), max(0.0, deadline - time.monotonic())))
            continue
        logger.debug(
            "f1_api_response source=%s url=%s status=%d attempt=%d duration_ms=%d",
            source,
            url,
            response.status_code,
            attempt + 1,
            round((time.monotonic() - started) * 1_000),
        )
        if response.status_code not in RETRYABLE_STATUSES or attempt + 1 == MAX_ATTEMPTS:
            break
        delay = min(_retry_delay(response, attempt), max(0.0, deadline - time.monotonic()))
        logger.warning(
            "f1_api_retry source=%s status=%d attempt=%d delay_seconds=%.3f",
            source,
            response.status_code,
            attempt + 1,
            delay,
        )
        time.sleep(delay)

    assert response is not None
    if empty_on_404 and response.status_code == 404:
        result = ApiResponse(payload=[], ttl=ttl)
    elif not response.is_success:
        raise F1ApiError(source, response.status_code, response.text)
    else:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"{source} returned a non-JSON response") from exc
        origin_ttl = _max_age(response)
        result = ApiResponse(payload=payload, ttl=max(ttl, origin_ttl or 0))
    _CACHE.store(key, result)
    return result


def _client(client: httpx.Client | None) -> httpx.Client:
    return client if client is not None else httpx.Client(timeout=TIMEOUT, follow_redirects=True)


# --- Jolpica-F1 -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JolpicaResult:
    """Items collected from every page of one Jolpica table, plus their cache lifetime."""

    items: list[dict[str, Any]]
    ttl: int
    context: dict[str, Any]


_JOLPICA_TABLES = {
    "Races": "RaceTable",
    "StandingsLists": "StandingsTable",
    "Seasons": "SeasonTable",
    "Drivers": "DriverTable",
    "Constructors": "ConstructorTable",
    "Circuits": "CircuitTable",
}
# Per-race child arrays that Jolpica splits across pages.
_RACE_CHILDREN = ("Results", "SprintResults", "QualifyingResults", "Laps", "PitStops")


def _merge_races(items: list[dict[str, Any]], page: list[dict[str, Any]]) -> None:
    """Append a page of races, joining a race whose children continue from the last page."""
    for race in page:
        previous = items[-1] if items else None
        if (
            previous is not None
            and previous.get("season") == race.get("season")
            and previous.get("round") == race.get("round")
        ):
            for child in _RACE_CHILDREN:
                if isinstance(race.get(child), list):
                    previous.setdefault(child, []).extend(race[child])
        else:
            items.append(race)


def _merge_laps(race: dict[str, Any]) -> None:
    """Combine lap entries split across pages into one entry per lap number."""
    laps = race.get("Laps")
    if not isinstance(laps, list):
        return
    merged: dict[str, dict[str, Any]] = {}
    for lap in laps:
        if not isinstance(lap, dict):
            continue
        entry = merged.setdefault(str(lap.get("number")), {"number": lap.get("number"), "Timings": []})
        if isinstance(lap.get("Timings"), list):
            entry["Timings"].extend(lap["Timings"])
    race["Laps"] = list(merged.values())


def is_historical(season: int | None) -> bool:
    """Return whether a season has finished, so its data no longer changes."""
    return season is not None and season < datetime.now(UTC).year


@dataclass(frozen=True, slots=True)
class JolpicaPage:
    """One page of a Jolpica table plus what is needed to request the next one."""

    items: list[dict[str, Any]]
    ttl: int
    context: dict[str, Any]
    next_offset: int | None


def _check_list_key(list_key: str) -> str:
    if list_key not in _JOLPICA_TABLES:
        raise ValueError(f"unsupported Jolpica list {list_key!r}")
    return _JOLPICA_TABLES[list_key]


def fetch_jolpica_page(
    path: str,
    list_key: str,
    *,
    offset: int = 0,
    historical: bool = False,
    client: httpx.Client | None = None,
) -> JolpicaPage:
    """Fetch one 100-row page of a Jolpica-F1 resource such as ``2024/5/results``.

    ``list_key`` names the array inside the resource's table, for example
    ``Races`` or ``StandingsLists``. ``next_offset`` is ``None`` on the last page.
    """
    table_key = _check_list_key(list_key)
    if offset >= JOLPICA_PAGE_SIZE * JOLPICA_MAX_PAGES:
        raise RuntimeError(f"Jolpica-F1 pagination for {path} exceeded {JOLPICA_MAX_PAGES} pages")
    http = _client(client)
    try:
        response = _get(
            source="Jolpica-F1",
            url=f"{jolpica_base_url()}/{path.strip('/')}.json",
            params={"limit": JOLPICA_PAGE_SIZE, "offset": offset},
            limiter=_JOLPICA_LIMITER,
            ttl=HISTORICAL_TTL if historical else CURRENT_TTL,
            deadline=time.monotonic() + QUERY_TIMEOUT,
            client=http,
        )
    finally:
        if client is None:
            http.close()
    data = response.payload.get("MRData") if isinstance(response.payload, dict) else None
    table = data.get(table_key) if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(table, dict):
        raise ValueError(f"Jolpica-F1 response for {path} has no {table_key}")
    try:
        total = int(data.get("total", 0))
        limit = int(data.get("limit", JOLPICA_PAGE_SIZE))
    except (TypeError, ValueError):
        total, limit = 0, JOLPICA_PAGE_SIZE
    following = offset + limit
    return JolpicaPage(
        items=[value for value in table.get(list_key) or [] if isinstance(value, dict)],
        ttl=response.ttl,
        context={key: value for key, value in table.items() if not isinstance(value, list)},
        next_offset=following if limit > 0 and following < total else None,
    )


def fetch_jolpica(
    path: str,
    list_key: str,
    *,
    historical: bool = False,
    client: httpx.Client | None = None,
) -> JolpicaResult:
    """Fetch and join every page of a Jolpica-F1 resource.

    Races whose child rows continue onto the next page are rejoined, so callers
    see complete races rather than an unexplained 100-row prefix.
    """
    _check_list_key(list_key)
    items: list[dict[str, Any]] = []
    ttls: list[int] = []
    context: dict[str, Any] = {}
    http = _client(client)
    try:
        offset: int | None = 0
        while offset is not None:
            page = fetch_jolpica_page(path, list_key, offset=offset, historical=historical, client=http)
            ttls.append(page.ttl)
            context = page.context
            if list_key == "Races":
                _merge_races(items, page.items)
            else:
                items.extend(page.items)
            offset = page.next_offset
    finally:
        if client is None:
            http.close()
    if list_key == "Races":
        for race in items:
            _merge_laps(race)
    return JolpicaResult(items=items, ttl=min(ttls), context=context)


# --- OpenF1 -----------------------------------------------------------------------------------


def fetch_openf1(
    resource: str,
    params: Mapping[str, str | int],
    *,
    ttl: int = HISTORICAL_TTL,
    client: httpx.Client | None = None,
) -> ApiResponse:
    """Fetch one OpenF1 resource; OpenF1 returns 404 when a filter matches nothing."""
    url = f"{openf1_base_url()}/{resource.strip('/')}"
    http = _client(client)
    try:
        response = _get(
            source="OpenF1",
            url=url,
            params=params,
            limiter=_OPENF1_LIMITER,
            ttl=ttl,
            deadline=time.monotonic() + QUERY_TIMEOUT,
            client=http,
            empty_on_404=True,
        )
    finally:
        if client is None:
            http.close()
    if not isinstance(response.payload, list):
        raise ValueError(f"OpenF1 {resource} response is not a JSON array")
    rows = [value for value in response.payload if isinstance(value, dict)]
    return ApiResponse(payload=rows, ttl=response.ttl)
