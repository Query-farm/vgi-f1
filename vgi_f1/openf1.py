"""Table functions over OpenF1's keyless historical session data (2023 onwards)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

import pyarrow as pa
from vgi.arguments import Arg

from vgi_f1 import api
from vgi_f1.examples import TYRE_STRATEGY_BY_FINISH
from vgi_f1.functions import Example, Fetched, table_function
from vgi_f1.schemas import (
    MEETINGS_SCHEMA,
    RACE_CONTROL_SCHEMA,
    SESSION_DRIVERS_SCHEMA,
    SESSION_LAPS_SCHEMA,
    SESSION_PITS_SCHEMA,
    SESSION_RESULT_SCHEMA,
    SESSION_STINTS_SCHEMA,
    SESSION_WEATHER_SCHEMA,
    SESSIONS_SCHEMA,
    TEAM_RADIO_SCHEMA,
    Row,
    flatten_meetings,
    flatten_race_control,
    flatten_session_drivers,
    flatten_session_laps,
    flatten_session_pits,
    flatten_session_result,
    flatten_session_stints,
    flatten_session_weather,
    flatten_sessions,
    flatten_team_radio,
)

FIRST_SEASON = 2023
SOURCE = "openf1"
SESSION_NAMES = (
    "Race",
    "Qualifying",
    "Sprint",
    "Sprint Qualifying",
    "Sprint Shootout",
    "Practice 1",
    "Practice 2",
    "Practice 3",
    "Day 1",
    "Day 2",
    "Day 3",
)
# Finished sessions are immutable, but OpenF1 publishes historical data shortly
# after a session ends, so a just-finished session is re-read after an hour.
SESSION_TTL = 3_600

_SEASON = Arg(0, arrow_type=pa.int32(), ge=FIRST_SEASON, doc="Season year, 2023 or later.")
_SESSION_KEY = Arg(
    0, arrow_type=pa.int32(), ge=1, doc="OpenF1 session key, as returned by sessions(), for example 9472."
)
_DRIVER_NUMBER = Arg(
    "driver_number",
    default=None,
    arrow_type=pa.int32(),
    ge=1,
    le=99,
    doc="Optional car number to restrict the result to one driver.",
)


@dataclass(kw_only=True)
class MeetingArgs:
    """A required season."""

    season: Annotated[int, _SEASON]


@dataclass(kw_only=True)
class SessionListArgs:
    """A required season and an optional session name."""

    season: Annotated[int, _SEASON]
    session_name: Annotated[
        str | None,
        Arg(
            "session_name",
            default=None,
            arrow_type=pa.string(),
            choices=SESSION_NAMES,
            doc="Optional session name such as Race, Qualifying, or Sprint.",
        ),
    ]


@dataclass(kw_only=True)
class SessionArgs:
    """A required session key."""

    session_key: Annotated[int, _SESSION_KEY]


@dataclass(kw_only=True)
class SessionDriverArgs:
    """A required session key with an optional driver filter."""

    session_key: Annotated[int, _SESSION_KEY]
    driver_number: Annotated[int | None, _DRIVER_NUMBER]


def _fetch(
    resource: str,
    params: Mapping[str, str | int | None],
    flatten: Callable[[Iterable[Mapping[str, Any]]], list[Row]],
    *,
    ttl: int = SESSION_TTL,
) -> Fetched:
    query = {key: value for key, value in params.items() if value is not None}
    response = api.fetch_openf1(resource, query, ttl=ttl)
    return Fetched(rows=flatten(response.payload), ttl=response.ttl)


def _season_ttl(season: int) -> int:
    return api.HISTORICAL_TTL if api.is_historical(season) else api.CURRENT_TTL


MeetingsFunction = table_function(
    name="meetings",
    args=MeetingArgs,
    schema=MEETINGS_SCHEMA,
    fetch=lambda args: _fetch(
        "meetings", {"year": args.season}, flatten_meetings, ttl=_season_ttl(args.season)
    ),
    title="F1 Race Weekends (OpenF1)",
    description="OpenF1 meetings (race weekends and tests) for a season, 2023 onwards",
    category="sessions",
    doc_llm=(
        "One row per race weekend or test in a season from 2023, with OpenF1's meeting_key, "
        "official event name, circuit, country, and UTC start and end."
    ),
    doc_md="OpenF1 meetings. `meeting_key` links to `sessions()`.",
    examples=[
        Example(
            "2024 race weekends on street circuits.",
            "SELECT meeting_name, location FROM f1.main.meetings(2024) "
            "WHERE circuit_type LIKE '%Street%' ORDER BY date_start",
        )
    ],
    estimate=25,
    maximum=40,
    source=SOURCE,
)

SessionsFunction = table_function(
    name="sessions",
    args=SessionListArgs,
    schema=SESSIONS_SCHEMA,
    fetch=lambda args: _fetch(
        "sessions",
        {"year": args.season, "session_name": args.session_name},
        flatten_sessions,
        ttl=_season_ttl(args.season),
    ),
    title="F1 Sessions (OpenF1)",
    description="OpenF1 sessions for a season (2023 onwards), optionally filtered by session name",
    category="sessions",
    doc_llm=(
        "One row per practice, qualifying, sprint, or race session from 2023, with the "
        "session_key every session_* function takes. Filter with session_name := 'Race'. To find "
        "one race, filter by country_name or location and date_start."
    ),
    doc_md=(
        "OpenF1 sessions. Look up `session_key` here, then pass it to `session_result()`, "
        "`session_laps()`, `session_stints()`, `session_pits()`, `session_weather()`, "
        "`race_control()`, `team_radio()`, or `session_drivers()`."
    ),
    examples=[
        Example(
            "Session keys for every 2024 race.",
            "SELECT session_key, country_name, location, date_start "
            "FROM f1.main.sessions(2024, session_name := 'Race') ORDER BY date_start",
        )
    ],
    estimate=120,
    maximum=200,
    source=SOURCE,
)

SessionDriversFunction = table_function(
    name="session_drivers",
    args=SessionArgs,
    schema=SESSION_DRIVERS_SCHEMA,
    fetch=lambda args: _fetch("drivers", {"session_key": args.session_key}, flatten_session_drivers),
    title="F1 Session Entry List (OpenF1)",
    description="Drivers, car numbers, and teams taking part in one OpenF1 session",
    category="sessions",
    doc_llm=(
        "One row per driver in a session, mapping driver_number to name acronym, full name, and "
        "team. Join it to the other session_* functions on driver_number."
    ),
    doc_md="The session entry list; the join key for OpenF1 timing data is `driver_number`.",
    examples=[
        Example(
            "Entry list for the 2024 Bahrain Grand Prix (session 9472).",
            "SELECT driver_number, name_acronym, full_name, team_name FROM f1.main.session_drivers(9472) "
            "ORDER BY driver_number",
        )
    ],
    estimate=20,
    maximum=30,
    source=SOURCE,
)

SessionResultFunction = table_function(
    name="session_result",
    args=SessionArgs,
    schema=SESSION_RESULT_SCHEMA,
    fetch=lambda args: _fetch("session_result", {"session_key": args.session_key}, flatten_session_result),
    title="F1 Session Classification (OpenF1)",
    description="Final classification of one OpenF1 session: race, sprint, qualifying, or practice",
    category="results",
    doc_llm=(
        "One row per driver with final position, laps, points, DNF/DNS/DSQ flags, total time, "
        "and gap to the leader. For qualifying sessions q1/q2/q3_seconds hold each phase's best "
        "lap. Lapped gaps such as '+1 LAP' stay in gap_to_leader with a null numeric gap."
    ),
    doc_md=(
        "Session classification. Numeric gaps are seconds as `DOUBLE`; the published value "
        "remains in `gap_to_leader`."
    ),
    examples=[
        Example(
            "Top ten of the 2024 Bahrain Grand Prix with driver names.",
            "SELECT r.position, d.full_name, r.points, r.gap_to_leader "
            "FROM f1.main.session_result(9472) r JOIN f1.main.session_drivers(9472) d "
            "USING (driver_number) WHERE r.position <= 10 ORDER BY r.position",
        )
    ],
    estimate=20,
    maximum=30,
    source=SOURCE,
)

SessionLapsFunction = table_function(
    name="session_laps",
    args=SessionDriverArgs,
    schema=SESSION_LAPS_SCHEMA,
    fetch=lambda args: _fetch(
        "laps",
        {"session_key": args.session_key, "driver_number": args.driver_number},
        flatten_session_laps,
    ),
    title="F1 Session Laps and Sectors (OpenF1)",
    description="Lap and sector times with speed-trap readings for one OpenF1 session",
    category="timing",
    doc_llm=(
        "One row per driver per lap with lap and sector durations in seconds, intermediate and "
        "speed-trap speeds, and pit-out flags. Requires a session_key; driver_number narrows it "
        "to one car. Lap times are null for laps without a valid timing (for example lap 1)."
    ),
    doc_md="Lap and sector timing for one session. Durations are seconds as `DOUBLE`.",
    examples=[
        Example(
            "Fastest race laps in the 2024 Bahrain Grand Prix.",
            "SELECT driver_number, lap_number, lap_duration FROM f1.main.session_laps(9472) "
            "WHERE lap_duration IS NOT NULL ORDER BY lap_duration LIMIT 5",
        )
    ],
    estimate=1_100,
    maximum=2_500,
    source=SOURCE,
)

SessionStintsFunction = table_function(
    name="session_stints",
    args=SessionArgs,
    schema=SESSION_STINTS_SCHEMA,
    fetch=lambda args: _fetch("stints", {"session_key": args.session_key}, flatten_session_stints),
    title="F1 Tyre Stints (OpenF1)",
    description="Tyre stints (compound, laps, tyre age) for every driver in one OpenF1 session",
    category="timing",
    doc_llm=(
        "One row per stint per driver with tyre compound, first and last lap, and tyre age at "
        "the start. Use it to reconstruct race strategies."
    ),
    doc_md="Tyre stints for one session; `lap_end - lap_start + 1` is the stint length.",
    examples=[
        Example(
            "Compound usage in the 2024 Bahrain Grand Prix.",
            "SELECT compound, count(*) AS stints, sum(lap_end - lap_start + 1) AS laps "
            "FROM f1.main.session_stints(9472) GROUP BY compound ORDER BY laps DESC",
        ),
        TYRE_STRATEGY_BY_FINISH,
    ],
    estimate=60,
    maximum=200,
    source=SOURCE,
)

SessionPitsFunction = table_function(
    name="session_pits",
    args=SessionArgs,
    schema=SESSION_PITS_SCHEMA,
    fetch=lambda args: _fetch("pit", {"session_key": args.session_key}, flatten_session_pits),
    title="F1 Session Pit Stops (OpenF1)",
    description="Pit stops with pit-lane and stationary durations for one OpenF1 session",
    category="timing",
    doc_llm=(
        "One row per pit stop with lap, UTC time, pit-lane duration, and (in newer sessions) "
        "stationary stop duration in seconds."
    ),
    doc_md="Pit stops for one session. `stop_duration` is null where OpenF1 does not publish it.",
    examples=[
        Example(
            "Quickest pit-lane visits in the 2024 Bahrain Grand Prix.",
            "SELECT driver_number, lap_number, lane_duration FROM f1.main.session_pits(9472) "
            "ORDER BY lane_duration LIMIT 5",
        )
    ],
    estimate=45,
    maximum=150,
    source=SOURCE,
)

SessionWeatherFunction = table_function(
    name="session_weather",
    args=SessionArgs,
    schema=SESSION_WEATHER_SCHEMA,
    fetch=lambda args: _fetch("weather", {"session_key": args.session_key}, flatten_session_weather),
    title="F1 Session Weather (OpenF1)",
    description="Track-side weather samples, about one per minute, for one OpenF1 session",
    category="sessions",
    doc_llm=(
        "One row per weather sample with air and track temperature, humidity, pressure, rainfall, "
        "and wind. Aggregate it for session conditions."
    ),
    doc_md="Weather samples; temperatures are degrees Celsius and wind speed is metres per second.",
    examples=[
        Example(
            "Track temperature range during the 2024 Bahrain Grand Prix.",
            "SELECT min(track_temperature) AS coolest, max(track_temperature) AS hottest, "
            "bool_or(rainfall) AS any_rain FROM f1.main.session_weather(9472)",
        )
    ],
    estimate=160,
    maximum=600,
    source=SOURCE,
)

RaceControlFunction = table_function(
    name="race_control",
    args=SessionArgs,
    schema=RACE_CONTROL_SCHEMA,
    fetch=lambda args: _fetch("race_control", {"session_key": args.session_key}, flatten_race_control),
    title="F1 Race Control Messages (OpenF1)",
    description="Race control messages (flags, safety car, penalties, DRS) for one OpenF1 session",
    category="sessions",
    doc_llm=(
        "One row per race control message: flags, safety car and virtual safety car periods, "
        "track limits and penalties, DRS status, and session status, with lap and UTC time."
    ),
    doc_md="Race control messages in time order. Filter on `category` or `flag`.",
    examples=[
        Example(
            "Flags shown in the 2024 Bahrain Grand Prix.",
            "SELECT date, lap_number, flag, scope, message FROM f1.main.race_control(9472) "
            "WHERE category = 'Flag' ORDER BY date",
        )
    ],
    estimate=80,
    maximum=500,
    source=SOURCE,
)

TeamRadioFunction = table_function(
    name="team_radio",
    args=SessionDriverArgs,
    schema=TEAM_RADIO_SCHEMA,
    fetch=lambda args: _fetch(
        "team_radio",
        {"session_key": args.session_key, "driver_number": args.driver_number},
        flatten_team_radio,
    ),
    title="F1 Team Radio Clips (OpenF1)",
    description="Links to broadcast team radio clips for one OpenF1 session",
    category="sessions",
    doc_llm=(
        "One row per broadcast team radio clip with UTC time, driver number, and a link to the "
        "official audio. Only clips that were broadcast are included; audio is not rehosted."
    ),
    doc_md="Team radio clip links. Audio stays on Formula 1's servers.",
    examples=[
        Example(
            "Radio clips per driver in the 2024 Bahrain Grand Prix.",
            "SELECT driver_number, count(*) AS clips FROM f1.main.team_radio(9472) "
            "GROUP BY driver_number ORDER BY clips DESC",
        )
    ],
    estimate=140,
    maximum=500,
    source=SOURCE,
)

FUNCTIONS = [
    MeetingsFunction,
    SessionsFunction,
    SessionDriversFunction,
    SessionResultFunction,
    SessionLapsFunction,
    SessionStintsFunction,
    SessionPitsFunction,
    SessionWeatherFunction,
    RaceControlFunction,
    TeamRadioFunction,
]
