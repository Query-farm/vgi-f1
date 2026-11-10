"""Typed Arrow schemas and flattening for Jolpica-F1 and OpenF1 responses."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pyarrow as pa

from vgi_f1.meta import field

POINTS = pa.decimal128(7, 2)
SECONDS = pa.decimal128(10, 3)
TIMESTAMP = pa.timestamp("us", tz="UTC")

Row = dict[str, Any]

# --- value parsing ----------------------------------------------------------------------------


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def to_int(value: Any) -> int | None:
    """Parse an integer-like API value without treating booleans as integers."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def to_float(value: Any) -> float | None:
    """Parse a finite float, returning null for display markers such as '+1 LAP'."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def to_decimal(value: Any) -> Decimal | None:
    """Parse a finite decimal value, returning null for display markers."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def to_seconds(value: Any) -> Decimal | None:
    """Parse a lap or stop time such as ``1:32.608``, ``23.004`` or ``1:31:44.742`` to seconds."""
    if not isinstance(value, str) or not value or value.startswith("+"):
        return to_decimal(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
    total = Decimal(0)
    try:
        for part in value.split(":"):
            total = total * 60 + Decimal(part)
    except (InvalidOperation, ValueError):
        return None
    return total.quantize(Decimal("0.001")) if total.is_finite() else None


def to_date(value: Any) -> date | None:
    """Parse an ISO calendar date."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def to_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp into UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def session_timestamp(value: Any) -> datetime | None:
    """Combine a Jolpica ``{date, time}`` pair into a UTC timestamp; null without a time."""
    session = _mapping(value)
    day, clock = session.get("date"), session.get("time")
    if not isinstance(day, str) or not isinstance(clock, str):
        return None
    return to_timestamp(f"{day}T{clock}")


def to_bool(value: Any) -> bool | None:
    """Pass through JSON booleans only."""
    return value if isinstance(value, bool) else None


def batch_from_rows(rows: Sequence[Row], schema: pa.Schema) -> pa.RecordBatch:
    """Build a record batch in the declared column order."""
    return pa.RecordBatch.from_arrays(
        [pa.array([row.get(value.name) for row in rows], type=value.type) for value in schema],
        schema=schema,
    )


# --- shared Jolpica column groups -------------------------------------------------------------

_RACE_FIELDS = [
    field("season", pa.int32(), "Championship season year."),
    field("round", pa.int32(), "Round number within the season (1 = first race)."),
    field("race_name", pa.string(), "Grand Prix name, for example Bahrain Grand Prix."),
    field("race_date", pa.date32(), "Calendar date of the Grand Prix (local to the circuit)."),
    field("circuit_id", pa.string(), "Stable Jolpica/Ergast circuit identifier."),
    field("circuit_name", pa.string(), "Full circuit name, for example Autodromo Nazionale di Monza."),
    field("country", pa.string(), "Country of the circuit."),
]

_DRIVER_FIELDS = [
    field("driver_id", pa.string(), "Stable Jolpica/Ergast driver identifier, for example hamilton."),
    field("driver_code", pa.string(), "Three-letter driver code, for example HAM."),
    field("driver_name", pa.string(), "Driver's full name."),
    field("driver_nationality", pa.string(), "Nationality of the driver as a demonym, for example British."),
]

_CONSTRUCTOR_FIELDS = [
    field("constructor_id", pa.string(), "Stable Jolpica/Ergast constructor identifier."),
    field("constructor_name", pa.string(), "Constructor (team) name."),
]


def _race_columns(race: Mapping[str, Any]) -> Row:
    circuit = _mapping(race.get("Circuit"))
    location = _mapping(circuit.get("Location"))
    return {
        "season": to_int(race.get("season")),
        "round": to_int(race.get("round")),
        "race_name": race.get("raceName"),
        "race_date": to_date(race.get("date")),
        "circuit_id": circuit.get("circuitId"),
        "circuit_name": circuit.get("circuitName"),
        "country": location.get("country"),
    }


def _full_name(driver: Mapping[str, Any]) -> str | None:
    parts = [driver.get("givenName"), driver.get("familyName")]
    name = " ".join(part for part in parts if isinstance(part, str) and part)
    return name or None


def _driver_columns(driver: Mapping[str, Any]) -> Row:
    return {
        "driver_id": driver.get("driverId"),
        "driver_code": driver.get("code"),
        "driver_name": _full_name(driver),
        "driver_nationality": driver.get("nationality"),
    }


def _constructor_columns(constructor: Mapping[str, Any]) -> Row:
    return {
        "constructor_id": constructor.get("constructorId"),
        "constructor_name": constructor.get("name"),
    }


# --- seasons, drivers, constructors, circuits -------------------------------------------------

SEASONS_SCHEMA = pa.schema(
    [
        field("season", pa.int32(), "Championship season year."),
        field("wikipedia_url", pa.string(), "Wikipedia article for the season."),
    ]
)


def flatten_seasons(items: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per championship season."""
    return [{"season": to_int(item.get("season")), "wikipedia_url": item.get("url")} for item in items]


DRIVERS_SCHEMA = pa.schema(
    [
        field("driver_id", pa.string(), "Stable Jolpica/Ergast driver identifier."),
        field("driver_code", pa.string(), "Three-letter driver code, when assigned."),
        field("permanent_number", pa.int32(), "Driver's permanent car number, when assigned."),
        field("given_name", pa.string(), "Given name."),
        field("family_name", pa.string(), "Family name."),
        field("driver_name", pa.string(), "Full name."),
        field("date_of_birth", pa.date32(), "Date of birth."),
        field("nationality", pa.string(), "Nationality."),
        field("wikipedia_url", pa.string(), "Wikipedia article for the driver."),
    ]
)


def flatten_drivers(items: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per driver."""
    return [
        {
            "driver_id": item.get("driverId"),
            "driver_code": item.get("code"),
            "permanent_number": to_int(item.get("permanentNumber")),
            "given_name": item.get("givenName"),
            "family_name": item.get("familyName"),
            "driver_name": _full_name(item),
            "date_of_birth": to_date(item.get("dateOfBirth")),
            "nationality": item.get("nationality"),
            "wikipedia_url": item.get("url"),
        }
        for item in items
    ]


CONSTRUCTORS_SCHEMA = pa.schema(
    [
        field("constructor_id", pa.string(), "Stable Jolpica/Ergast constructor identifier."),
        field("constructor_name", pa.string(), "Constructor (team) name."),
        field("nationality", pa.string(), "Constructor nationality."),
        field("wikipedia_url", pa.string(), "Wikipedia article for the constructor."),
    ]
)


def flatten_constructors(items: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per constructor."""
    return [
        {
            "constructor_id": item.get("constructorId"),
            "constructor_name": item.get("name"),
            "nationality": item.get("nationality"),
            "wikipedia_url": item.get("url"),
        }
        for item in items
    ]


CIRCUITS_SCHEMA = pa.schema(
    [
        field("circuit_id", pa.string(), "Stable Jolpica/Ergast circuit identifier."),
        field("circuit_name", pa.string(), "Full circuit name, for example Autodromo Nazionale di Monza."),
        field("locality", pa.string(), "City or locality of the circuit."),
        field("country", pa.string(), "Country of the circuit."),
        field("latitude", pa.float64(), "Latitude in decimal degrees."),
        field("longitude", pa.float64(), "Longitude in decimal degrees."),
        field("wikipedia_url", pa.string(), "Wikipedia article for the circuit."),
    ]
)


def flatten_circuits(items: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per circuit."""
    rows = []
    for item in items:
        location = _mapping(item.get("Location"))
        rows.append(
            {
                "circuit_id": item.get("circuitId"),
                "circuit_name": item.get("circuitName"),
                "locality": location.get("locality"),
                "country": location.get("country"),
                "latitude": to_float(location.get("lat")),
                "longitude": to_float(location.get("long")),
                "wikipedia_url": item.get("url"),
            }
        )
    return rows


# --- schedule ---------------------------------------------------------------------------------

SCHEDULE_SCHEMA = pa.schema(
    [
        field("season", pa.int32(), "Championship season year."),
        field("round", pa.int32(), "Round number within the season (1 = first race)."),
        field("race_name", pa.string(), "Grand Prix name."),
        field("circuit_id", pa.string(), "Stable Jolpica/Ergast circuit identifier."),
        field("circuit_name", pa.string(), "Full circuit name, for example Autodromo Nazionale di Monza."),
        field("locality", pa.string(), "City or locality of the circuit."),
        field("country", pa.string(), "Country of the circuit."),
        field("race_date", pa.date32(), "Calendar date of the Grand Prix (local to the circuit)."),
        field("race_start_utc", TIMESTAMP, "Scheduled race start in UTC; null when no time is published."),
        field("first_practice_utc", TIMESTAMP, "First practice start in UTC."),
        field("second_practice_utc", TIMESTAMP, "Second practice start in UTC."),
        field("third_practice_utc", TIMESTAMP, "Third practice start in UTC; null on sprint weekends."),
        field("sprint_qualifying_utc", TIMESTAMP, "Sprint qualifying (or sprint shootout) start in UTC."),
        field("sprint_utc", TIMESTAMP, "Sprint race start in UTC; null on non-sprint weekends."),
        field("qualifying_utc", TIMESTAMP, "Grand Prix qualifying start in UTC."),
        field("is_sprint_weekend", pa.bool_(), "Whether the weekend includes a sprint race."),
        field("wikipedia_url", pa.string(), "Wikipedia article for the race."),
    ]
)


def flatten_schedule(races: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per championship round."""
    rows = []
    for race in races:
        circuit = _mapping(race.get("Circuit"))
        location = _mapping(circuit.get("Location"))
        sprint_qualifying = race.get("SprintQualifying") or race.get("SprintShootout")
        rows.append(
            {
                "season": to_int(race.get("season")),
                "round": to_int(race.get("round")),
                "race_name": race.get("raceName"),
                "circuit_id": circuit.get("circuitId"),
                "circuit_name": circuit.get("circuitName"),
                "locality": location.get("locality"),
                "country": location.get("country"),
                "race_date": to_date(race.get("date")),
                "race_start_utc": session_timestamp(race),
                "first_practice_utc": session_timestamp(race.get("FirstPractice")),
                "second_practice_utc": session_timestamp(race.get("SecondPractice")),
                "third_practice_utc": session_timestamp(race.get("ThirdPractice")),
                "sprint_qualifying_utc": session_timestamp(sprint_qualifying),
                "sprint_utc": session_timestamp(race.get("Sprint")),
                "qualifying_utc": session_timestamp(race.get("Qualifying")),
                "is_sprint_weekend": "Sprint" in race,
                "wikipedia_url": race.get("url"),
            }
        )
    return rows


# --- standings --------------------------------------------------------------------------------

DRIVER_STANDINGS_SCHEMA = pa.schema(
    [
        field("season", pa.int32(), "Championship season year."),
        field("round", pa.int32(), "Round number after which these standings apply."),
        field("position", pa.int32(), "Championship position (1 = leader); null when unclassified."),
        field("position_text", pa.string(), "Championship position as published, '-' when unclassified."),
        field("points", POINTS, "Count of championship points as an exact decimal (half points exist)."),
        field("wins", pa.int32(), "Number of Grand Prix wins so far this season."),
        field("driver_id", pa.string(), "Stable Jolpica/Ergast driver identifier."),
        field("driver_code", pa.string(), "Three-letter driver code."),
        field("permanent_number", pa.int32(), "Driver's permanent car number (chosen race number)."),
        field("driver_name", pa.string(), "Driver's full name."),
        field(
            "driver_nationality", pa.string(), "Nationality of the driver as a demonym, for example British."
        ),
        field(
            "constructor_id",
            pa.string(),
            "Constructor identifier when the driver raced for exactly one team; null otherwise.",
        ),
        field(
            "constructor_name",
            pa.string(),
            "Constructor name when the driver raced for exactly one team; null otherwise.",
        ),
        field("constructor_ids", pa.string(), "Comma-separated constructor identifiers this season."),
        field("constructor_names", pa.string(), "Comma-separated constructor names this season."),
    ]
)

CONSTRUCTOR_STANDINGS_SCHEMA = pa.schema(
    [
        field("season", pa.int32(), "Championship season year."),
        field("round", pa.int32(), "Round number after which these standings apply."),
        field(
            "position",
            pa.int32(),
            "Constructors' championship position (1 = leader); null when unclassified.",
        ),
        field("position_text", pa.string(), "Championship position as published."),
        field("points", POINTS, "Count of constructors' championship points as an exact decimal."),
        field("wins", pa.int32(), "Number of Grand Prix wins so far this season."),
        field("constructor_id", pa.string(), "Stable Jolpica/Ergast constructor identifier."),
        field("constructor_name", pa.string(), "Constructor (team) name."),
        field(
            "constructor_nationality",
            pa.string(),
            "Nationality the team races under, as a demonym, for example Italian.",
        ),
    ]
)


def flatten_driver_standings(lists: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per driver per standings list."""
    rows = []
    for standings in lists:
        for entry in standings.get("DriverStandings") or []:
            if not isinstance(entry, Mapping):
                continue
            driver = _mapping(entry.get("Driver"))
            constructors = [_mapping(value) for value in entry.get("Constructors") or []]
            ids = [value.get("constructorId") for value in constructors if value.get("constructorId")]
            names = [value.get("name") for value in constructors if value.get("name")]
            rows.append(
                {
                    "season": to_int(standings.get("season")),
                    "round": to_int(standings.get("round")),
                    "position": to_int(entry.get("position")),
                    "position_text": entry.get("positionText"),
                    "points": to_decimal(entry.get("points")),
                    "wins": to_int(entry.get("wins")),
                    **_driver_columns(driver),
                    "permanent_number": to_int(driver.get("permanentNumber")),
                    "constructor_id": ids[0] if len(ids) == 1 else None,
                    "constructor_name": names[0] if len(names) == 1 else None,
                    "constructor_ids": ", ".join(ids) or None,
                    "constructor_names": ", ".join(names) or None,
                }
            )
    return rows


def flatten_constructor_standings(lists: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per constructor per standings list."""
    rows = []
    for standings in lists:
        for entry in standings.get("ConstructorStandings") or []:
            if not isinstance(entry, Mapping):
                continue
            constructor = _mapping(entry.get("Constructor"))
            rows.append(
                {
                    "season": to_int(standings.get("season")),
                    "round": to_int(standings.get("round")),
                    "position": to_int(entry.get("position")),
                    "position_text": entry.get("positionText"),
                    "points": to_decimal(entry.get("points")),
                    "wins": to_int(entry.get("wins")),
                    **_constructor_columns(constructor),
                    "constructor_nationality": constructor.get("nationality"),
                }
            )
    return rows


# --- race and sprint results ------------------------------------------------------------------

RESULTS_SCHEMA = pa.schema(
    [
        *_RACE_FIELDS,
        field("position", pa.int32(), "Finishing position (classification order, including retirements)."),
        field(
            "position_text",
            pa.string(),
            "Published classification: a number, or R retired, D disqualified, E excluded, "
            "W withdrawn, F failed to qualify, N not classified.",
        ),
        field("classified", pa.bool_(), "Whether position_text is numeric, i.e. the driver was classified."),
        field("points", POINTS, "Championship points scored in this race."),
        field("car_number", pa.int32(), "Race number displayed on the car (not a position)."),
        *_DRIVER_FIELDS,
        *_CONSTRUCTOR_FIELDS,
        field("grid", pa.int32(), "Starting grid position (1 = pole); 0 means a pit-lane start."),
        field("laps", pa.int32(), "Number of laps completed."),
        field("status", pa.string(), "Finishing status, for example Finished, +1 Lap, or Engine."),
        field(
            "race_time_millis", pa.int64(), "Total race time in milliseconds for finishers on the lead lap."
        ),
        field("race_time", pa.string(), "Published race time: absolute for the winner, a gap for others."),
        field(
            "fastest_lap_rank",
            pa.int32(),
            "Rank of this driver's fastest lap among all drivers (1 = fastest).",
        ),
        field("fastest_lap_number", pa.int32(), "Lap number on which the driver set their fastest lap."),
        field("fastest_lap_time", pa.string(), "Fastest lap time as published, for example 1:32.608."),
        field("fastest_lap_seconds", SECONDS, "Fastest lap time in seconds as an exact decimal."),
        field("fastest_lap_avg_speed_kph", pa.float64(), "Average speed of the fastest lap in km/h."),
    ]
)


def flatten_results(races: Iterable[Mapping[str, Any]], *, key: str = "Results") -> list[Row]:
    """One row per driver per race; ``key`` selects Results or SprintResults."""
    rows = []
    for race in races:
        base = _race_columns(race)
        for entry in race.get(key) or []:
            if not isinstance(entry, Mapping):
                continue
            fastest = _mapping(entry.get("FastestLap"))
            fastest_time = _mapping(fastest.get("Time")).get("time")
            race_time = _mapping(entry.get("Time"))
            position_text = entry.get("positionText")
            rows.append(
                {
                    **base,
                    "position": to_int(entry.get("position")),
                    "position_text": position_text,
                    "classified": isinstance(position_text, str) and position_text.isdigit(),
                    "points": to_decimal(entry.get("points")),
                    "car_number": to_int(entry.get("number")),
                    **_driver_columns(_mapping(entry.get("Driver"))),
                    **_constructor_columns(_mapping(entry.get("Constructor"))),
                    "grid": to_int(entry.get("grid")),
                    "laps": to_int(entry.get("laps")),
                    "status": entry.get("status"),
                    "race_time_millis": to_int(race_time.get("millis")),
                    "race_time": race_time.get("time"),
                    "fastest_lap_rank": to_int(fastest.get("rank")),
                    "fastest_lap_number": to_int(fastest.get("lap")),
                    "fastest_lap_time": fastest_time,
                    "fastest_lap_seconds": to_seconds(fastest_time),
                    "fastest_lap_avg_speed_kph": to_float(_mapping(fastest.get("AverageSpeed")).get("speed")),
                }
            )
    return rows


def flatten_sprint_results(races: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per driver per sprint race."""
    return flatten_results(races, key="SprintResults")


# --- qualifying -------------------------------------------------------------------------------

QUALIFYING_SCHEMA = pa.schema(
    [
        *_RACE_FIELDS,
        field("position", pa.int32(), "Qualifying classification position."),
        field("car_number", pa.int32(), "Car number."),
        *_DRIVER_FIELDS,
        *_CONSTRUCTOR_FIELDS,
        field("q1", pa.string(), "Best Q1 lap time as published; null if no time was set."),
        field("q2", pa.string(), "Best Q2 lap time as published; null if eliminated in Q1."),
        field("q3", pa.string(), "Best Q3 lap time as published; null if eliminated before Q3."),
        field("q1_seconds", SECONDS, "Best Q1 lap time in seconds."),
        field("q2_seconds", SECONDS, "Best Q2 lap time in seconds."),
        field("q3_seconds", SECONDS, "Best Q3 lap time in seconds."),
    ]
)


def flatten_qualifying(races: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per driver per qualifying session."""
    rows = []
    for race in races:
        base = _race_columns(race)
        for entry in race.get("QualifyingResults") or []:
            if not isinstance(entry, Mapping):
                continue
            rows.append(
                {
                    **base,
                    "position": to_int(entry.get("position")),
                    "car_number": to_int(entry.get("number")),
                    **_driver_columns(_mapping(entry.get("Driver"))),
                    **_constructor_columns(_mapping(entry.get("Constructor"))),
                    **{phase: entry.get(phase.upper()) or None for phase in ("q1", "q2", "q3")},
                    **{
                        f"{phase}_seconds": to_seconds(entry.get(phase.upper()))
                        for phase in ("q1", "q2", "q3")
                    },
                }
            )
    return rows


# --- laps and pit stops -----------------------------------------------------------------------

LAP_TIMES_SCHEMA = pa.schema(
    [
        field("season", pa.int32(), "Championship season year."),
        field("round", pa.int32(), "Round number within the season (1 = first race)."),
        field("race_name", pa.string(), "Grand Prix name."),
        field("lap", pa.int32(), "Lap number."),
        field("driver_id", pa.string(), "Stable Jolpica/Ergast driver identifier."),
        field("position", pa.int32(), "Running position at the end of the lap."),
        field("lap_time", pa.string(), "Lap time as published, for example 1:41.528."),
        field("lap_time_seconds", SECONDS, "Lap time in seconds as an exact decimal."),
    ]
)


def flatten_lap_times(races: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per driver per lap."""
    rows = []
    for race in races:
        for lap in race.get("Laps") or []:
            if not isinstance(lap, Mapping):
                continue
            for timing in lap.get("Timings") or []:
                if not isinstance(timing, Mapping):
                    continue
                rows.append(
                    {
                        "season": to_int(race.get("season")),
                        "round": to_int(race.get("round")),
                        "race_name": race.get("raceName"),
                        "lap": to_int(lap.get("number")),
                        "driver_id": timing.get("driverId"),
                        "position": to_int(timing.get("position")),
                        "lap_time": timing.get("time"),
                        "lap_time_seconds": to_seconds(timing.get("time")),
                    }
                )
    rows.sort(key=lambda row: (row["lap"] or 0, row["position"] or 999))
    return rows


PIT_STOPS_SCHEMA = pa.schema(
    [
        field("season", pa.int32(), "Championship season year."),
        field("round", pa.int32(), "Round number within the season (1 = first race)."),
        field("race_name", pa.string(), "Grand Prix name."),
        field("driver_id", pa.string(), "Stable Jolpica/Ergast driver identifier."),
        field("stop", pa.int32(), "Stop number for this driver in this race."),
        field("lap", pa.int32(), "Lap on which the stop was made."),
        field("time_of_day", pa.string(), "Local time of day of the stop, as published."),
        field(
            "duration", pa.string(), "Pit-lane duration as published (entry to exit, not stationary time)."
        ),
        field("duration_seconds", SECONDS, "Pit-lane duration in seconds as an exact decimal."),
    ]
)


def flatten_pit_stops(races: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per pit stop."""
    rows = []
    for race in races:
        for stop in race.get("PitStops") or []:
            if not isinstance(stop, Mapping):
                continue
            rows.append(
                {
                    "season": to_int(race.get("season")),
                    "round": to_int(race.get("round")),
                    "race_name": race.get("raceName"),
                    "driver_id": stop.get("driverId"),
                    "stop": to_int(stop.get("stop")),
                    "lap": to_int(stop.get("lap")),
                    "time_of_day": stop.get("time"),
                    "duration": stop.get("duration"),
                    "duration_seconds": to_seconds(stop.get("duration")),
                }
            )
    return rows


# --- OpenF1 -----------------------------------------------------------------------------------

_SESSION_KEY = field("session_key", pa.int32(), "OpenF1 session key.")
_MEETING_KEY = field("meeting_key", pa.int32(), "OpenF1 meeting (race weekend) key.")
_DRIVER_NUMBER = field("driver_number", pa.int32(), "Car number of the driver in this session.")

MEETINGS_SCHEMA = pa.schema(
    [
        field("meeting_key", pa.int32(), "OpenF1 meeting (race weekend) key."),
        field("meeting_name", pa.string(), "Meeting name, for example Bahrain Grand Prix."),
        field("meeting_official_name", pa.string(), "Official sponsored event name."),
        field("year", pa.int32(), "Season year."),
        field("location", pa.string(), "Meeting location."),
        field("country_code", pa.string(), "Three-letter country code."),
        field("country_name", pa.string(), "Country name."),
        field("circuit_key", pa.int32(), "OpenF1 circuit key."),
        field("circuit_short_name", pa.string(), "Short circuit name."),
        field("circuit_type", pa.string(), "Circuit type, for example Permanent or Temporary - Street."),
        field("date_start", TIMESTAMP, "Start of the meeting in UTC."),
        field("date_end", TIMESTAMP, "End of the meeting in UTC."),
        field("gmt_offset", pa.string(), "Local UTC offset of the venue, for example 03:00:00."),
        field("is_cancelled", pa.bool_(), "Whether the meeting was cancelled."),
    ]
)

SESSIONS_SCHEMA = pa.schema(
    [
        field("session_key", pa.int32(), "OpenF1 session key; pass it to the session_* functions."),
        _MEETING_KEY,
        field("session_name", pa.string(), "Session name, for example Race, Qualifying, Sprint, Practice 1."),
        field("session_type", pa.string(), "Session type, for example Race, Qualifying, Practice."),
        field("year", pa.int32(), "Season year."),
        field("location", pa.string(), "Session location."),
        field("country_code", pa.string(), "Three-letter country code."),
        field("country_name", pa.string(), "Country name."),
        field("circuit_key", pa.int32(), "OpenF1 circuit key."),
        field("circuit_short_name", pa.string(), "Short circuit name."),
        field("date_start", TIMESTAMP, "Session start in UTC."),
        field("date_end", TIMESTAMP, "Session end in UTC."),
        field("gmt_offset", pa.string(), "Local UTC offset of the venue."),
        field("is_cancelled", pa.bool_(), "Whether the session was cancelled."),
    ]
)

SESSION_DRIVERS_SCHEMA = pa.schema(
    [
        _SESSION_KEY,
        _MEETING_KEY,
        field("driver_number", pa.int32(), "Car number of the driver in this session."),
        field("name_acronym", pa.string(), "Three-letter driver acronym, for example VER."),
        field("broadcast_name", pa.string(), "Name as shown on the TV graphics."),
        field("full_name", pa.string(), "Full name as published by OpenF1."),
        field("first_name", pa.string(), "First name."),
        field("last_name", pa.string(), "Last name."),
        field("team_name", pa.string(), "Team name."),
        field("team_colour", pa.string(), "Team colour as a hexadecimal RGB string."),
        field("country_code", pa.string(), "Driver's three-letter country code."),
    ]
)

SESSION_LAPS_SCHEMA = pa.schema(
    [
        _SESSION_KEY,
        _MEETING_KEY,
        _DRIVER_NUMBER,
        field("lap_number", pa.int32(), "Lap number."),
        field("date_start", TIMESTAMP, "Time the lap started, in UTC."),
        field("lap_duration", pa.float64(), "Lap time in seconds; null for laps without a valid time."),
        field("duration_sector_1", pa.float64(), "Sector 1 time in seconds."),
        field("duration_sector_2", pa.float64(), "Sector 2 time in seconds."),
        field("duration_sector_3", pa.float64(), "Sector 3 time in seconds."),
        field("i1_speed", pa.int32(), "Speed at intermediate 1 in km/h."),
        field("i2_speed", pa.int32(), "Speed at intermediate 2 in km/h."),
        field("st_speed", pa.int32(), "Speed at the speed trap in km/h."),
        field("is_pit_out_lap", pa.bool_(), "Whether the lap began in the pit lane."),
    ]
)

SESSION_STINTS_SCHEMA = pa.schema(
    [
        _SESSION_KEY,
        _MEETING_KEY,
        _DRIVER_NUMBER,
        field("stint_number", pa.int32(), "Stint number for this driver, starting at 1."),
        field("lap_start", pa.int32(), "First lap of the stint."),
        field("lap_end", pa.int32(), "Last lap of the stint."),
        field("compound", pa.string(), "Tyre compound: SOFT, MEDIUM, HARD, INTERMEDIATE, or WET."),
        field("tyre_age_at_start", pa.int32(), "Laps already on the tyre set when the stint began."),
    ]
)

SESSION_PITS_SCHEMA = pa.schema(
    [
        _SESSION_KEY,
        _MEETING_KEY,
        _DRIVER_NUMBER,
        field("date", TIMESTAMP, "Time of the pit entry, in UTC."),
        field("lap_number", pa.int32(), "Lap on which the stop was made."),
        field("lane_duration", pa.float64(), "Time spent in the pit lane, in seconds."),
        field("stop_duration", pa.float64(), "Stationary time in seconds, where OpenF1 publishes it."),
    ]
)

SESSION_WEATHER_SCHEMA = pa.schema(
    [
        _SESSION_KEY,
        _MEETING_KEY,
        field("date", TIMESTAMP, "Time of the sample, in UTC (roughly one per minute)."),
        field("air_temperature", pa.float64(), "Air temperature in degrees Celsius."),
        field("track_temperature", pa.float64(), "Track surface temperature in degrees Celsius."),
        field("humidity", pa.float64(), "Relative humidity in percent."),
        field("pressure", pa.float64(), "Air pressure in millibars."),
        field("rainfall", pa.bool_(), "Whether rain was falling."),
        field("wind_direction", pa.int32(), "Wind direction in degrees (0-359)."),
        field("wind_speed", pa.float64(), "Wind speed in metres per second."),
    ]
)

RACE_CONTROL_SCHEMA = pa.schema(
    [
        _SESSION_KEY,
        _MEETING_KEY,
        field("date", TIMESTAMP, "Time of the message, in UTC."),
        field("lap_number", pa.int32(), "Race lap at the time of the message."),
        field(
            "category", pa.string(), "Message category: Flag, SafetyCar, Drs, CarEvent, SessionStatus, Other."
        ),
        field("flag", pa.string(), "Flag shown, for example GREEN, YELLOW, RED, CHEQUERED."),
        field("scope", pa.string(), "Flag scope: Track, Sector, or Driver."),
        field("sector", pa.int32(), "Marshal sector for sector-scoped flags."),
        field("driver_number", pa.int32(), "Driver concerned, when the message targets one car."),
        field("qualifying_phase", pa.int32(), "Qualifying phase (1-3) for qualifying messages."),
        field("message", pa.string(), "Race control message text."),
    ]
)

SESSION_RESULT_SCHEMA = pa.schema(
    [
        _SESSION_KEY,
        _MEETING_KEY,
        field("position", pa.int32(), "Final classified position; null when not classified."),
        _DRIVER_NUMBER,
        field("number_of_laps", pa.int32(), "Laps completed."),
        field("points", POINTS, "Points scored, for race and sprint sessions."),
        field("dnf", pa.bool_(), "Did not finish."),
        field("dns", pa.bool_(), "Did not start."),
        field("dsq", pa.bool_(), "Disqualified."),
        field("duration_seconds", pa.float64(), "Total race time in seconds, or best lap in practice."),
        field("gap_to_leader_seconds", pa.float64(), "Gap to the winner in seconds; null when lapped."),
        field("gap_to_leader", pa.string(), "Gap to the winner as published, for example 22.457 or +1 LAP."),
        field("q1_seconds", pa.float64(), "Best Q1 time in seconds (qualifying sessions)."),
        field("q2_seconds", pa.float64(), "Best Q2 time in seconds (qualifying sessions)."),
        field("q3_seconds", pa.float64(), "Best Q3 time in seconds (qualifying sessions)."),
    ]
)

TEAM_RADIO_SCHEMA = pa.schema(
    [
        _SESSION_KEY,
        _MEETING_KEY,
        _DRIVER_NUMBER,
        field("date", TIMESTAMP, "Time of the radio message, in UTC."),
        field("recording_url", pa.string(), "Link to the official audio clip on Formula 1 live timing."),
    ]
)


def _openf1_flattener(
    spec: Mapping[str, Callable[[Any], Any]],
) -> Callable[[Iterable[Mapping[str, Any]]], list[Row]]:
    def flatten(items: Iterable[Mapping[str, Any]]) -> list[Row]:
        return [{name: parse(item.get(name)) for name, parse in spec.items()} for item in items]

    return flatten


def _identity(value: Any) -> Any:
    return value if isinstance(value, str) else None


def _parsers(schema: pa.Schema) -> dict[str, Callable[[Any], Any]]:
    parsers: dict[str, Callable[[Any], Any]] = {}
    for value in schema:
        kind = value.type
        if pa.types.is_timestamp(kind):
            parsers[value.name] = to_timestamp
        elif pa.types.is_integer(kind):
            parsers[value.name] = to_int
        elif pa.types.is_floating(kind):
            parsers[value.name] = to_float
        elif pa.types.is_decimal(kind):
            parsers[value.name] = to_decimal
        elif pa.types.is_boolean(kind):
            parsers[value.name] = to_bool
        else:
            parsers[value.name] = _identity
    return parsers


flatten_meetings = _openf1_flattener(_parsers(MEETINGS_SCHEMA))
flatten_sessions = _openf1_flattener(_parsers(SESSIONS_SCHEMA))
flatten_session_drivers = _openf1_flattener(_parsers(SESSION_DRIVERS_SCHEMA))
flatten_session_laps = _openf1_flattener(_parsers(SESSION_LAPS_SCHEMA))
flatten_session_stints = _openf1_flattener(_parsers(SESSION_STINTS_SCHEMA))
flatten_race_control = _openf1_flattener(_parsers(RACE_CONTROL_SCHEMA))
flatten_team_radio = _openf1_flattener(_parsers(TEAM_RADIO_SCHEMA))

_pit_parsers = _parsers(SESSION_PITS_SCHEMA)


def flatten_session_pits(items: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per pit stop; older OpenF1 rows only publish ``pit_duration``."""
    rows = []
    for item in items:
        row = {name: parse(item.get(name)) for name, parse in _pit_parsers.items()}
        if row["lane_duration"] is None:
            row["lane_duration"] = to_float(item.get("pit_duration"))
        rows.append(row)
    return rows


def flatten_session_weather(items: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per weather sample; OpenF1 reports rainfall as 0 or 1."""
    parsers = _parsers(SESSION_WEATHER_SCHEMA)
    rows = []
    for item in items:
        row = {name: parse(item.get(name)) for name, parse in parsers.items()}
        rainfall = item.get("rainfall")
        row["rainfall"] = bool(rainfall) if isinstance(rainfall, int | float) else to_bool(rainfall)
        rows.append(row)
    return rows


def _phase(values: Any, index: int) -> float | None:
    return to_float(values[index]) if isinstance(values, list) and len(values) > index else None


def flatten_session_result(items: Iterable[Mapping[str, Any]]) -> list[Row]:
    """One row per driver; qualifying sessions publish per-phase lists instead of scalars."""
    rows = []
    for item in items:
        duration, gap = item.get("duration"), item.get("gap_to_leader")
        rows.append(
            {
                "session_key": to_int(item.get("session_key")),
                "meeting_key": to_int(item.get("meeting_key")),
                "position": to_int(item.get("position")),
                "driver_number": to_int(item.get("driver_number")),
                "number_of_laps": to_int(item.get("number_of_laps")),
                "points": to_decimal(item.get("points")),
                "dnf": to_bool(item.get("dnf")),
                "dns": to_bool(item.get("dns")),
                "dsq": to_bool(item.get("dsq")),
                "duration_seconds": None if isinstance(duration, list) else to_float(duration),
                "gap_to_leader_seconds": None if isinstance(gap, list) else to_float(gap),
                "gap_to_leader": None if gap is None or isinstance(gap, list) else str(gap),
                "q1_seconds": _phase(duration, 0),
                "q2_seconds": _phase(duration, 1),
                "q3_seconds": _phase(duration, 2),
            }
        )
    rows.sort(key=lambda row: (row["position"] is None, row["position"] or 0, row["driver_number"] or 0))
    return rows
