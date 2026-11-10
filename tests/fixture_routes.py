"""Map upstream request paths to the trimmed real responses in ``tests/fixtures``.

Shared by the in-process unit tests (through ``httpx.MockTransport``) and the
hermetic Haybarn end-to-end test (through a local HTTP server), so both
exercise the same recorded Jolpica-F1 and OpenF1 payloads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"

JOLPICA = {
    "current/driverStandings.json": "jolpica_current_driver_standings.json",
    "current/constructorStandings.json": "jolpica_current_constructor_standings.json",
    "current/races.json": "jolpica_current_races.json",
    "current/last/results.json": "jolpica_current_last_results.json",
    "seasons.json": "jolpica_seasons.json",
    "2024/races.json": "jolpica_2024_races.json",
    "2024/driverStandings.json": "jolpica_2024_driver_standings.json",
    "2024/constructorStandings.json": "jolpica_2024_constructor_standings.json",
    "2024/results.json": "jolpica_2024_results.json",
    "2024/sprint.json": "jolpica_2024_sprint.json",
    "2024/5/qualifying.json": "jolpica_2024_5_qualifying.json",
    "2024/5/laps.json": "jolpica_2024_5_laps.json",
    "2024/5/drivers/max_verstappen/laps.json": "jolpica_2024_5_laps.json",
    "2024/5/pitstops.json": "jolpica_2024_5_pitstops.json",
    "2024/drivers.json": "jolpica_2024_drivers.json",
    "2024/constructors.json": "jolpica_2024_constructors.json",
    "2024/circuits.json": "jolpica_2024_circuits.json",
    "drivers/hamilton/results.json": "jolpica_hamilton_results.json",
}

# Resources served in small pages so tests exercise Jolpica's row-based pagination,
# where one race's results continue on the next page.
PAGE_SIZES = {"2024/results.json": 4}

OPENF1 = {
    ("meetings", "2024"): "openf1_meetings_2024.json",
    ("sessions", "2024"): "openf1_sessions_2024_race.json",
    ("drivers", "9472"): "openf1_drivers_9472.json",
    ("laps", "9472"): "openf1_laps_9472.json",
    ("stints", "9472"): "openf1_stints_9472.json",
    ("pit", "9472"): "openf1_pit_9472.json",
    ("weather", "9472"): "openf1_weather_9472.json",
    ("race_control", "9472"): "openf1_race_control_9472.json",
    ("session_result", "9472"): "openf1_session_result_9472.json",
    ("session_result", "9468"): "openf1_session_result_9468.json",
    ("team_radio", "9472"): "openf1_team_radio_9472.json",
}


def load(name: str) -> Any:
    """Return one fixture's decoded JSON."""
    return json.loads((FIXTURES / name).read_text())


def _page(payload: dict[str, Any], offset: int, limit: int) -> dict[str, Any]:
    """Slice a Races payload by result row, as Jolpica does."""
    data = payload["MRData"]
    rows = [(race, result) for race in data["RaceTable"]["Races"] for result in race["Results"]][
        offset : offset + limit
    ]
    races: list[dict[str, Any]] = []
    for race, result in rows:
        if not races or races[-1]["round"] != race["round"]:
            races.append({**race, "Results": []})
        races[-1]["Results"].append(result)
    data.update(limit=str(limit), offset=str(offset))
    data["RaceTable"]["Races"] = races
    return payload


def resolve(source: str, path: str, query: dict[str, str]) -> tuple[int, Any]:
    """Return ``(status, payload)`` for a request relative to a source's base URL."""
    path = path.strip("/")
    if source == "jolpica":
        name = JOLPICA.get(path)
        if not name:
            return 404, {"detail": "Not found."}
        payload = load(name)
        if path in PAGE_SIZES:
            payload = _page(payload, int(query.get("offset", 0)), PAGE_SIZES[path])
        return 200, payload
    key = query.get("session_key") or query.get("year") or ""
    name = OPENF1.get((path, key))
    return (200, load(name)) if name else (404, load("openf1_not_found.json"))
