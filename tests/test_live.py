"""Opt-in smoke tests against the public Jolpica-F1 and OpenF1 APIs.

Pinned to the finished 2024 season wherever possible so the assertions are
stable facts rather than moving live data.
"""

from decimal import Decimal

import pytest

from vgi_f1 import api, schemas


@pytest.mark.live
def test_current_championship_points_balance() -> None:
    drivers = schemas.flatten_driver_standings(
        api.fetch_jolpica("current/driverStandings", "StandingsLists").items
    )
    constructors = schemas.flatten_constructor_standings(
        api.fetch_jolpica("current/constructorStandings", "StandingsLists").items
    )
    assert len(drivers) >= 20
    assert len(constructors) >= 10
    assert all(row["driver_id"] for row in drivers)
    # Every driver point is also a constructor point (no team-only penalties in the modern era).
    assert sum(row["points"] for row in drivers) == sum(row["points"] for row in constructors)


@pytest.mark.live
def test_2024_final_standings() -> None:
    rows = schemas.flatten_driver_standings(api.fetch_jolpica("2024/driverStandings", "StandingsLists").items)
    champion = rows[0]
    assert champion["driver_id"] == "max_verstappen"
    assert champion["points"] == Decimal("437")
    assert champion["wins"] == 9


@pytest.mark.live
def test_2024_results_are_fully_paged() -> None:
    rows = schemas.flatten_results(api.fetch_jolpica("2024/results", "Races", historical=True).items)
    assert len(rows) == 479
    assert len({row["round"] for row in rows}) == 24
    winners = [row for row in rows if row["position"] == 1]
    assert sum(1 for row in winners if row["driver_id"] == "max_verstappen") == 9


@pytest.mark.live
def test_2024_chinese_gp_laps_and_stops() -> None:
    laps = schemas.flatten_lap_times(
        api.fetch_jolpica("2024/5/drivers/max_verstappen/laps", "Races", historical=True).items
    )
    assert len(laps) == 56
    stops = schemas.flatten_pit_stops(api.fetch_jolpica("2024/5/pitstops", "Races", historical=True).items)
    assert {row["stop"] for row in stops if row["driver_id"] == "max_verstappen"} == {1, 2}


@pytest.mark.live
def test_openf1_bahrain_2024_race() -> None:
    sessions = schemas.flatten_sessions(
        api.fetch_openf1("sessions", {"year": 2024, "session_name": "Race"}).payload
    )
    bahrain = next(row for row in sessions if row["country_name"] == "Bahrain")
    assert bahrain["session_key"] == 9472
    result = schemas.flatten_session_result(api.fetch_openf1("session_result", {"session_key": 9472}).payload)
    assert result[0]["driver_number"] == 1
    assert result[0]["duration_seconds"] == pytest.approx(5504.742)
    stints = schemas.flatten_session_stints(
        api.fetch_openf1("stints", {"session_key": 9472, "driver_number": 1}).payload
    )
    assert [row["compound"] for row in stints] == ["SOFT", "HARD", "SOFT"]
