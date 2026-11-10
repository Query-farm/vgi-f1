"""Shared test configuration: hermetic base URLs, fresh client state, fixture transport."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fixture_routes import resolve

from vgi_f1 import api

JOLPICA_TEST_ROOT = "https://jolpica.test/ergast/f1"
OPENF1_TEST_ROOT = "https://openf1.test/v1"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[None]:
    """Point offline tests at unroutable hosts and reset the cache and rate limiters."""
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setenv("F1_JOLPICA_BASE_URL", JOLPICA_TEST_ROOT)
        monkeypatch.setenv("F1_OPENF1_BASE_URL", OPENF1_TEST_ROOT)
    api.reset_state()
    yield
    api.reset_state()


def fixture_handler(request: httpx.Request) -> httpx.Response:
    """Serve recorded fixtures for both upstream hosts."""
    url = str(request.url.copy_with(query=None))
    query = dict(request.url.params)
    if url.startswith(JOLPICA_TEST_ROOT):
        status, payload = resolve("jolpica", url.removeprefix(JOLPICA_TEST_ROOT), query)
        headers = {"Cache-Control": "max-age=600"}
    elif url.startswith(OPENF1_TEST_ROOT):
        status, payload = resolve("openf1", url.removeprefix(OPENF1_TEST_ROOT), query)
        headers = {}
    else:  # pragma: no cover - a test bug
        raise AssertionError(f"unexpected URL {url}")
    return httpx.Response(status, json=payload, headers=headers)


@pytest.fixture
def fixture_transport(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Route every client the API module creates through the fixture handler."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return fixture_handler(request)

    def client(existing: httpx.Client | None) -> httpx.Client:
        return existing or httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    monkeypatch.setattr(api, "_client", client)
    return seen
