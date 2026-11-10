"""Parsing and Arrow-schema tests over trimmed real Jolpica-F1 and OpenF1 responses."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pyarrow as pa
import pytest
from fixture_routes import load

from vgi_f1 import schemas
from vgi_f1.meta import comment_of, result_columns_schema


def _items(name: str, table: str, key: str) -> list[dict]:
    return load(name)["MRData"][table][key]


ALL_SCHEMAS = [value for name, value in vars(schemas).items() if name.endswith("_SCHEMA")]


@pytest.mark.parametrize("schema", ALL_SCHEMAS)
def test_every_column_is_documented(schema: pa.Schema) -> None:
    assert all(comment_of(value) for value in schema)
    assert len(set(schema.names)) == len(schema.names)
    result_columns_schema(schema)


def test_result_columns_schema_rejects_unknown_types() -> None:
    with pytest.raises(ValueError, match="Unsupported F1 result type"):
        result_columns_schema(pa.schema([pa.field("x", pa.list_(pa.int8()), metadata={b"comment": b"x"})]))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1:32.608", Decimal("92.608")),
        ("23.004", Decimal("23.004")),
        ("1:31:44.742", Decimal("5504.742")),
        ("16:44.123", Decimal("1004.123")),
        ("+18.595", None),
        ("", None),
        (None, None),
        ("abc", None),
        (12.5, Decimal("12.5")),
        (True, None),
    ],
)
def test_to_seconds(value, expected) -> None:
    assert schemas.to_seconds(value) == expected


def test_scalar_parsers() -> None:
    assert schemas.to_int("7") == 7
    assert schemas.to_int(True) is None
    assert schemas.to_int("x") is None
    assert schemas.to_float("+1 LAP") is None
    assert schemas.to_float(float("nan")) is None
    assert schemas.to_float(float("inf")) is None
    assert schemas.to_decimal("0.5") == Decimal("0.5")
    assert schemas.to_decimal("Infinity") is None
    assert schemas.to_decimal("x") is None
    assert schemas.to_date("2024-13-01") is None
    assert schemas.to_timestamp("2024-03-02T15:00:00") == datetime(2024, 3, 2, 15, tzinfo=UTC)
    assert schemas.to_timestamp("garbage") is None
    assert schemas.session_timestamp({"date": "2024-03-02"}) is None
    assert schemas.to_bool(1) is None


def test_driver_standings() -> None:
    rows = schemas.flatten_driver_standings(
        _items("jolpica_current_driver_standings.json", "StandingsTable", "StandingsLists")
    )
    assert len(rows) == 5
    leader = rows[0]
    assert leader["season"] == 2026
    assert leader["position"] == 1
    assert leader["driver_id"] == "antonelli"
    assert leader["driver_name"] == "Andrea Kimi Antonelli"
    assert leader["points"] == Decimal("390")
    assert leader["constructor_id"] == "mercedes"
    batch = schemas.batch_from_rows(rows, schemas.DRIVER_STANDINGS_SCHEMA)
    assert batch.schema == schemas.DRIVER_STANDINGS_SCHEMA


def test_multi_team_driver_has_no_single_constructor() -> None:
    standings = [
        {
            "season": "2024",
            "round": "24",
            "DriverStandings": [
                {
                    "position": "18",
                    "positionText": "18",
                    "points": "7",
                    "wins": "0",
                    "Driver": {"driverId": "bearman", "givenName": "Oliver", "familyName": "Bearman"},
                    "Constructors": [
                        {"constructorId": "ferrari", "name": "Ferrari"},
                        {"constructorId": "haas", "name": "Haas F1 Team"},
                    ],
                },
                "not-a-mapping",
            ],
        }
    ]
    [row] = schemas.flatten_driver_standings(standings)
    assert row["constructor_id"] is None
    assert row["constructor_ids"] == "ferrari, haas"
    assert row["constructor_names"] == "Ferrari, Haas F1 Team"


def test_constructor_standings() -> None:
    rows = schemas.flatten_constructor_standings(
        _items("jolpica_current_constructor_standings.json", "StandingsTable", "StandingsLists")
    )
    assert [row["constructor_id"] for row in rows][:2] == ["mercedes", "ferrari"]
    assert rows[0]["points"] == Decimal("652")
    schemas.batch_from_rows(rows, schemas.CONSTRUCTOR_STANDINGS_SCHEMA)


def test_schedule_with_sprint_weekend() -> None:
    rows = schemas.flatten_schedule(_items("jolpica_current_races.json", "RaceTable", "Races"))
    assert [row["round"] for row in rows] == [1, 2, 3]
    assert rows[0]["is_sprint_weekend"] is False
    assert rows[0]["sprint_utc"] is None
    assert rows[0]["race_start_utc"] == datetime(2026, 3, 8, 4, tzinfo=UTC)
    assert rows[1]["is_sprint_weekend"] is True
    assert rows[1]["sprint_utc"] is not None
    assert rows[1]["sprint_qualifying_utc"] is not None
    assert rows[1]["third_practice_utc"] is None
    schemas.batch_from_rows(rows, schemas.SCHEDULE_SCHEMA)


def test_race_results() -> None:
    rows = schemas.flatten_results(_items("jolpica_2024_results.json", "RaceTable", "Races"))
    winner = rows[0]
    assert winner["race_name"] == "Bahrain Grand Prix"
    assert winner["race_date"] == date(2024, 3, 2)
    assert winner["driver_id"] == "max_verstappen"
    assert winner["classified"] is True
    assert winner["points"] == Decimal("26")
    assert winner["race_time_millis"] == 5_504_742
    assert winner["fastest_lap_seconds"] == Decimal("92.608")
    assert winner["fastest_lap_avg_speed_kph"] == pytest.approx(210.383)
    assert {row["round"] for row in rows} == {1, 2}
    schemas.batch_from_rows(rows, schemas.RESULTS_SCHEMA)


def test_last_race_results() -> None:
    rows = schemas.flatten_results(_items("jolpica_current_last_results.json", "RaceTable", "Races"))
    assert rows[0]["race_name"] == "Brazilian Grand Prix"
    assert rows[0]["driver_id"] == "norris"
    assert rows[0]["fastest_lap_avg_speed_kph"] is None


def test_retirement_is_not_classified() -> None:
    race = {
        "season": "2024",
        "round": "1",
        "Results": [{"position": "20", "positionText": "R", "status": "Brakes"}],
    }
    [row] = schemas.flatten_results([race])
    assert row["position"] == 20
    assert row["classified"] is False


def test_blank_published_times_are_null() -> None:
    # Jolpica publishes {"millis": "...", "time": ""} for some retirements (2024 round 3, Russell).
    race = {
        "season": "2024",
        "round": "3",
        "Results": [
            {
                "position": "17",
                "positionText": "R",
                "status": "Retired",
                "Time": {"millis": "4684734", "time": ""},
                "FastestLap": {"rank": "5", "lap": "50", "Time": {"time": ""}},
            }
        ],
    }
    [row] = schemas.flatten_results([race])
    assert row["race_time"] is None
    assert row["race_time_millis"] == 4_684_734
    assert row["fastest_lap_time"] is None
    assert row["fastest_lap_seconds"] is None


def test_sprint_results() -> None:
    rows = schemas.flatten_sprint_results(_items("jolpica_2024_sprint.json", "RaceTable", "Races"))
    assert rows[0]["round"] == 5
    assert rows[0]["driver_id"] == "max_verstappen"
    assert rows[0]["points"] == Decimal("8")


def test_qualifying() -> None:
    rows = schemas.flatten_qualifying(_items("jolpica_2024_5_qualifying.json", "RaceTable", "Races"))
    pole = rows[0]
    assert pole["position"] == 1
    assert pole["q3"] == "1:33.660"
    assert pole["q3_seconds"] == Decimal("93.660")
    assert pole["q1_seconds"] == Decimal("94.742")
    schemas.batch_from_rows(rows, schemas.QUALIFYING_SCHEMA)


def test_lap_times() -> None:
    rows = schemas.flatten_lap_times(_items("jolpica_2024_5_laps.json", "RaceTable", "Races"))
    assert len(rows) == 6
    assert rows[0] == {
        "season": 2024,
        "round": 5,
        "race_name": "Chinese Grand Prix",
        "lap": 1,
        "driver_id": "max_verstappen",
        "position": 1,
        "lap_time": "1:41.528",
        "lap_time_seconds": Decimal("101.528"),
    }
    schemas.batch_from_rows(rows, schemas.LAP_TIMES_SCHEMA)


def test_pit_stops() -> None:
    rows = schemas.flatten_pit_stops(_items("jolpica_2024_5_pitstops.json", "RaceTable", "Races"))
    assert rows[0]["driver_id"] == "hulkenberg"
    assert rows[0]["duration_seconds"] == Decimal("23.004")
    assert rows[0]["stop"] == 1
    schemas.batch_from_rows(rows, schemas.PIT_STOPS_SCHEMA)


def test_reference_tables() -> None:
    seasons = schemas.flatten_seasons(_items("jolpica_seasons.json", "SeasonTable", "Seasons"))
    assert seasons[0] == {
        "season": 1950,
        "wikipedia_url": "https://en.wikipedia.org/wiki/1950_Formula_One_season",
    }
    drivers = schemas.flatten_drivers(_items("jolpica_2024_drivers.json", "DriverTable", "Drivers"))
    assert drivers[0]["driver_id"] == "albon"
    assert drivers[0]["date_of_birth"] == date(1996, 3, 23)
    assert drivers[0]["permanent_number"] == 23
    constructors = schemas.flatten_constructors(
        _items("jolpica_2024_constructors.json", "ConstructorTable", "Constructors")
    )
    assert constructors[0]["constructor_id"] == "alpine"
    circuits = schemas.flatten_circuits(_items("jolpica_2024_circuits.json", "CircuitTable", "Circuits"))
    assert circuits[0]["circuit_id"] == "albert_park"
    assert circuits[0]["latitude"] == pytest.approx(-37.8497)
    for rows, schema in [
        (seasons, schemas.SEASONS_SCHEMA),
        (drivers, schemas.DRIVERS_SCHEMA),
        (constructors, schemas.CONSTRUCTORS_SCHEMA),
        (circuits, schemas.CIRCUITS_SCHEMA),
    ]:
        assert schemas.batch_from_rows(rows, schema).num_rows == len(rows)


def test_openf1_sessions_and_meetings() -> None:
    sessions = schemas.flatten_sessions(load("openf1_sessions_2024_race.json"))
    assert sessions[0]["session_key"] == 9472
    assert sessions[0]["date_start"] == datetime(2024, 3, 2, 15, tzinfo=UTC)
    assert sessions[0]["is_cancelled"] is False
    meetings = schemas.flatten_meetings(load("openf1_meetings_2024.json"))
    assert meetings[1]["meeting_official_name"] == "FORMULA 1 GULF AIR BAHRAIN GRAND PRIX 2024"
    schemas.batch_from_rows(sessions, schemas.SESSIONS_SCHEMA)
    schemas.batch_from_rows(meetings, schemas.MEETINGS_SCHEMA)


def test_openf1_session_detail() -> None:
    drivers = schemas.flatten_session_drivers(load("openf1_drivers_9472.json"))
    assert drivers[0]["name_acronym"] == "VER"
    laps = schemas.flatten_session_laps(load("openf1_laps_9472.json"))
    assert laps[0]["lap_number"] == 1
    assert laps[0]["duration_sector_1"] == pytest.approx(32.877)
    stints = schemas.flatten_session_stints(load("openf1_stints_9472.json"))
    assert stints[0]["compound"] == "SOFT"
    pits = schemas.flatten_session_pits(load("openf1_pit_9472.json"))
    assert pits[0]["lane_duration"] == pytest.approx(36.6)
    assert schemas.flatten_session_pits([{"pit_duration": 21.5}])[0]["lane_duration"] == 21.5
    weather = schemas.flatten_session_weather(load("openf1_weather_9472.json"))
    assert weather[0]["rainfall"] is False
    assert weather[0]["air_temperature"] == pytest.approx(18.9)
    control = schemas.flatten_race_control(load("openf1_race_control_9472.json"))
    assert control[0]["category"] == "Other"
    radio = schemas.flatten_team_radio(load("openf1_team_radio_9472.json"))
    assert radio[0]["recording_url"].startswith("https://livetiming.formula1.com/")
    for rows, schema in [
        (drivers, schemas.SESSION_DRIVERS_SCHEMA),
        (laps, schemas.SESSION_LAPS_SCHEMA),
        (stints, schemas.SESSION_STINTS_SCHEMA),
        (pits, schemas.SESSION_PITS_SCHEMA),
        (weather, schemas.SESSION_WEATHER_SCHEMA),
        (control, schemas.RACE_CONTROL_SCHEMA),
        (radio, schemas.TEAM_RADIO_SCHEMA),
    ]:
        assert schemas.batch_from_rows(rows, schema).num_rows == len(rows)


def test_openf1_race_result_gaps() -> None:
    rows = schemas.flatten_session_result(load("openf1_session_result_9472.json"))
    assert rows[0]["position"] == 1
    assert rows[0]["gap_to_leader_seconds"] == 0
    assert rows[1]["gap_to_leader_seconds"] == pytest.approx(22.457)
    lapped = [row for row in rows if row["gap_to_leader"] == "+1 LAP"]
    assert lapped and all(row["gap_to_leader_seconds"] is None for row in lapped)
    assert rows[0]["points"] == Decimal("26.0")
    schemas.batch_from_rows(rows, schemas.SESSION_RESULT_SCHEMA)


def test_openf1_qualifying_result_phases() -> None:
    rows = schemas.flatten_session_result(load("openf1_session_result_9468.json"))
    pole = rows[0]
    assert pole["duration_seconds"] is None
    assert pole["gap_to_leader"] is None
    assert pole["q3_seconds"] == pytest.approx(89.179)
    assert pole["q1_seconds"] == pytest.approx(90.031)
    assert pole["points"] is None
