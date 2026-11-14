"""Table functions over Jolpica-F1, the Ergast-compatible results archive (1950-present)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

import pyarrow as pa
from vgi.arguments import Arg

from vgi_f1 import api
from vgi_f1.examples import SPRINT_VS_GRAND_PRIX_WINNERS, STINT_PACE
from vgi_f1.functions import Example, Paged, table_function
from vgi_f1.schemas import (
    CIRCUITS_SCHEMA,
    CONSTRUCTOR_STANDINGS_SCHEMA,
    CONSTRUCTORS_SCHEMA,
    DRIVER_STANDINGS_SCHEMA,
    DRIVERS_SCHEMA,
    LAP_TIMES_SCHEMA,
    PIT_STOPS_SCHEMA,
    QUALIFYING_SCHEMA,
    RESULTS_SCHEMA,
    SCHEDULE_SCHEMA,
    SEASONS_SCHEMA,
    Row,
    flatten_circuits,
    flatten_constructor_standings,
    flatten_constructors,
    flatten_driver_standings,
    flatten_drivers,
    flatten_lap_times,
    flatten_pit_stops,
    flatten_qualifying,
    flatten_results,
    flatten_schedule,
    flatten_seasons,
    flatten_sprint_results,
)

FIRST_SEASON = 1950
SOURCE = "jolpica-f1"
DRIVER_ID_PATTERN = r"^[a-z0-9_]+$"

_SEASON = Arg(0, arrow_type=pa.int32(), ge=FIRST_SEASON, doc="Championship season year, 1950 or later.")
_ROUND_POSITIONAL = Arg(1, arrow_type=pa.int32(), ge=1, doc="Round number within the season.")
_ROUND_OPTIONAL = Arg(
    "round",
    default=None,
    arrow_type=pa.int32(),
    ge=1,
    doc="Round number within the season. NULL returns every round of the season.",
)
_DRIVER_FILTER = Arg(
    "driver_id",
    default=None,
    arrow_type=pa.string(),
    pattern=DRIVER_ID_PATTERN,
    doc="Optional Jolpica/Ergast driver identifier such as max_verstappen.",
)
_OPTIONAL_SEASON = Arg(
    "season",
    default=None,
    arrow_type=pa.int32(),
    ge=FIRST_SEASON,
    doc="Season year. NULL returns every season since 1950.",
)


@dataclass(kw_only=True)
class SeasonArgs:
    """A required season."""

    season: Annotated[int, _SEASON]


@dataclass(kw_only=True)
class SeasonRoundArgs:
    """A required season with an optional round."""

    season: Annotated[int, _SEASON]
    round: Annotated[int | None, _ROUND_OPTIONAL]


@dataclass(kw_only=True)
class RaceArgs:
    """A required season and round."""

    season: Annotated[int, _SEASON]
    round: Annotated[int, _ROUND_POSITIONAL]


@dataclass(kw_only=True)
class LapArgs:
    """A required season and round with an optional driver filter."""

    season: Annotated[int, _SEASON]
    round: Annotated[int, _ROUND_POSITIONAL]
    driver_id: Annotated[str | None, _DRIVER_FILTER]


@dataclass(kw_only=True)
class OptionalSeasonArgs:
    """An optional season filter."""

    season: Annotated[int | None, _OPTIONAL_SEASON]


@dataclass(kw_only=True)
class DriverResultsArgs:
    """A required driver with an optional season."""

    driver_id: Annotated[
        str,
        Arg(0, arrow_type=pa.string(), pattern=DRIVER_ID_PATTERN, doc="Jolpica/Ergast driver identifier."),
    ]
    season: Annotated[int | None, _OPTIONAL_SEASON]


def _fetch(
    path: str,
    list_key: str,
    flatten: Callable[[Iterable[Mapping[str, Any]]], list[Row]],
    *,
    season: int | None = None,
) -> Paged:
    return Paged(path=path, list_key=list_key, flatten=flatten, historical=api.is_historical(season))


def _scoped(season: int, round_: int | None, resource: str) -> str:
    return f"{season}/{round_}/{resource}" if round_ is not None else f"{season}/{resource}"


# --- current-season tables --------------------------------------------------------------------

CurrentDriverStandingsFunction = table_function(
    name="all_current_driver_standings",
    args=None,
    schema=DRIVER_STANDINGS_SCHEMA,
    fetch=lambda _args: _fetch("current/driverStandings", "StandingsLists", flatten_driver_standings),
    title="Current Drivers' Championship (scan)",
    description="Current F1 drivers' championship standings (scan behind current_driver_standings)",
    category="standings",
    doc_llm=(
        "The scan behind the current_driver_standings table. Prefer the table; use "
        "driver_standings() for another season or the standings after a specific round."
    ),
    doc_md="Returns the current drivers' championship. Selecting `current_driver_standings` is clearer.",
    examples=[
        Example(
            "Current championship top five from the backing scan.",
            "SELECT position, driver_name, points FROM f1.main.all_current_driver_standings() "
            "ORDER BY position LIMIT 5",
        )
    ],
    estimate=22,
    maximum=40,
    source=SOURCE,
)

CurrentConstructorStandingsFunction = table_function(
    name="all_current_constructor_standings",
    args=None,
    schema=CONSTRUCTOR_STANDINGS_SCHEMA,
    fetch=lambda _args: _fetch(
        "current/constructorStandings", "StandingsLists", flatten_constructor_standings
    ),
    title="Current Constructors' Championship (scan)",
    description="Current F1 constructors' championship standings (scan behind current_constructor_standings)",
    category="standings",
    doc_llm=(
        "The scan behind the current_constructor_standings table. Prefer the table; use "
        "constructor_standings() for another season or a specific round."
    ),
    doc_md="Returns the current constructors' championship. Selecting the table is clearer.",
    examples=[
        Example(
            "Current constructors' leader from the backing scan.",
            "SELECT constructor_name, points FROM f1.main.all_current_constructor_standings() "
            "WHERE position = 1",
        )
    ],
    estimate=11,
    maximum=20,
    source=SOURCE,
)

CurrentScheduleFunction = table_function(
    name="all_current_schedule",
    args=None,
    schema=SCHEDULE_SCHEMA,
    fetch=lambda _args: _fetch("current/races", "Races", flatten_schedule),
    title="Current Season Calendar (scan)",
    description="Current F1 season calendar (scan behind current_schedule)",
    category="schedule",
    doc_llm="The scan behind the current_schedule table. Prefer the table; use schedule() for other seasons.",
    doc_md="Returns the current season calendar. Selecting `current_schedule` is clearer.",
    examples=[
        Example(
            "Sprint weekends this season from the backing scan.",
            "SELECT round, race_name FROM f1.main.all_current_schedule() WHERE is_sprint_weekend",
        )
    ],
    estimate=24,
    maximum=30,
    source=SOURCE,
)

LastRaceResultsFunction = table_function(
    name="all_last_race_results",
    args=None,
    schema=RESULTS_SCHEMA,
    fetch=lambda _args: _fetch("current/last/results", "Races", flatten_results),
    title="Latest Grand Prix Result (scan)",
    description="Classification of the most recent F1 Grand Prix (scan behind last_race_results)",
    category="results",
    doc_llm=(
        "The scan behind the last_race_results table. Prefer the table; use race_results() for "
        "any other race."
    ),
    doc_md="Returns the most recent Grand Prix classification. Selecting `last_race_results` is clearer.",
    examples=[
        Example(
            "Podium of the most recent race from the backing scan.",
            "SELECT position, driver_name, constructor_name FROM f1.main.all_last_race_results() "
            "WHERE position <= 3 ORDER BY position",
        )
    ],
    estimate=20,
    maximum=30,
    source=SOURCE,
)

# --- historical archive -----------------------------------------------------------------------

SeasonsFunction = table_function(
    name="all_seasons",
    args=None,
    schema=SEASONS_SCHEMA,
    fetch=lambda _args: _fetch("seasons", "Seasons", flatten_seasons, season=FIRST_SEASON),
    title="F1 Seasons (scan)",
    description="Every Formula 1 World Championship season since 1950 (scan behind seasons)",
    category="reference",
    doc_llm="The scan behind the seasons table. Prefer the table.",
    doc_md="Lists every championship season in the archive. Selecting `seasons` is clearer.",
    examples=[
        Example(
            "Number of championship seasons from the backing scan.",
            "SELECT count(*) AS seasons FROM f1.main.all_seasons()",
        )
    ],
    estimate=77,
    maximum=120,
    source=SOURCE,
)

ScheduleFunction = table_function(
    name="schedule",
    args=SeasonArgs,
    schema=SCHEDULE_SCHEMA,
    fetch=lambda args: _fetch(f"{args.season}/races", "Races", flatten_schedule, season=args.season),
    title="F1 Season Calendar",
    description="The race calendar for one F1 season, with UTC session start times",
    category="schedule",
    doc_llm=(
        "One row per round of the given season: Grand Prix name, circuit, country, race date and "
        "UTC start, practice, qualifying and sprint session starts, and whether it is a sprint "
        "weekend. Session times are null where the archive has none (most pre-2005 seasons)."
    ),
    doc_md=(
        "Season calendar. Session starts are `TIMESTAMP WITH TIME ZONE` values in UTC; "
        "`race_date` is always present even when no start time is published."
    ),
    examples=[
        Example(
            "The 2024 calendar in round order.",
            "SELECT round, race_name, country, race_date FROM f1.main.schedule(2024) ORDER BY round",
        )
    ],
    estimate=22,
    maximum=30,
    source=SOURCE,
)

DriverStandingsFunction = table_function(
    name="driver_standings",
    args=SeasonRoundArgs,
    schema=DRIVER_STANDINGS_SCHEMA,
    fetch=lambda args: _fetch(
        _scoped(args.season, args.round, "driverStandings"),
        "StandingsLists",
        flatten_driver_standings,
        season=args.season,
    ),
    title="F1 Drivers' Championship",
    description="Drivers' championship standings for a season, optionally after a given round",
    category="standings",
    doc_llm=(
        "One row per driver in the drivers' championship. Pass a season for the final (or "
        "latest) standings, and round := N for the standings after round N. Points are exact "
        "decimals. constructor_id is null when a driver raced for more than one team that season; "
        "constructor_ids lists every team."
    ),
    doc_md=(
        "Drivers' championship standings. `round := N` returns the table as it stood after "
        "round N. `position` is null for unclassified drivers while `position_text` keeps the "
        "published marker."
    ),
    examples=[
        Example(
            "Final 2024 drivers' championship.",
            "SELECT position, driver_name, constructor_name, points, wins "
            "FROM f1.main.driver_standings(2024) ORDER BY position",
        ),
        Example(
            "The 2024 championship after round 10.",
            "SELECT position, driver_name, points FROM f1.main.driver_standings(2024, round := 10) "
            "ORDER BY position LIMIT 5",
        ),
    ],
    estimate=22,
    maximum=60,
    source=SOURCE,
)

ConstructorStandingsFunction = table_function(
    name="constructor_standings",
    args=SeasonRoundArgs,
    schema=CONSTRUCTOR_STANDINGS_SCHEMA,
    fetch=lambda args: _fetch(
        _scoped(args.season, args.round, "constructorStandings"),
        "StandingsLists",
        flatten_constructor_standings,
        season=args.season,
    ),
    title="F1 Constructors' Championship",
    description="Constructors' championship standings for a season (1958 onwards), optionally after a round",
    category="standings",
    doc_llm=(
        "One row per constructor in the constructors' championship, which began in 1958 (earlier "
        "seasons return no rows). Use round := N for the standings after round N."
    ),
    doc_md="Constructors' championship standings with exact decimal points.",
    examples=[
        Example(
            "Final 2024 constructors' championship.",
            "SELECT position, constructor_name, points, wins FROM f1.main.constructor_standings(2024) "
            "ORDER BY position",
        )
    ],
    estimate=10,
    maximum=30,
    source=SOURCE,
)

RaceResultsFunction = table_function(
    name="race_results",
    args=SeasonRoundArgs,
    schema=RESULTS_SCHEMA,
    fetch=lambda args: _fetch(
        _scoped(args.season, args.round, "results"), "Races", flatten_results, season=args.season
    ),
    title="F1 Grand Prix Results",
    description="Grand Prix classifications for a season, or for one round",
    category="results",
    doc_llm=(
        "One row per driver per Grand Prix: finishing position, published classification, "
        "points, grid, laps, status, race time, and fastest lap. Pass round := N for one race; "
        "omit it for every race of the season (useful for counting wins or podiums). Sprint "
        "races are separate: use sprint_results()."
    ),
    doc_md=(
        "Grand Prix results. `position` is the classification order including retirements; "
        "`classified` is true only when `position_text` is numeric. `race_time_millis` is set for "
        "drivers on the lead lap. Fastest-lap seconds are exact decimals."
    ),
    examples=[
        Example(
            "Winners of every 2024 Grand Prix.",
            "SELECT round, race_name, driver_name, constructor_name FROM f1.main.race_results(2024) "
            "WHERE position = 1 ORDER BY round",
        ),
        Example(
            "Full classification of the 2024 Chinese Grand Prix (round 5).",
            "SELECT position, driver_name, grid, status, points "
            "FROM f1.main.race_results(2024, round := 5) ORDER BY position",
        ),
    ],
    estimate=480,
    maximum=1_000,
    source=SOURCE,
)

SprintResultsFunction = table_function(
    name="sprint_results",
    args=SeasonRoundArgs,
    schema=RESULTS_SCHEMA,
    fetch=lambda args: _fetch(
        _scoped(args.season, args.round, "sprint"), "Races", flatten_sprint_results, season=args.season
    ),
    title="F1 Sprint Results",
    description="Sprint race classifications for a season (2021 onwards), or for one round",
    category="results",
    doc_llm=(
        "One row per driver per sprint race, with the same columns as race_results(). Sprints "
        "began in 2021; non-sprint rounds return no rows."
    ),
    doc_md="Sprint race results with the same shape as `race_results()`.",
    examples=[
        Example(
            "Sprint winners in 2024.",
            "SELECT round, race_name, driver_name FROM f1.main.sprint_results(2024) "
            "WHERE position = 1 ORDER BY round",
        ),
        SPRINT_VS_GRAND_PRIX_WINNERS,
    ],
    estimate=120,
    maximum=200,
    source=SOURCE,
)

QualifyingResultsFunction = table_function(
    name="qualifying_results",
    args=SeasonRoundArgs,
    schema=QUALIFYING_SCHEMA,
    fetch=lambda args: _fetch(
        _scoped(args.season, args.round, "qualifying"), "Races", flatten_qualifying, season=args.season
    ),
    title="F1 Qualifying Results",
    description="Grand Prix qualifying classifications with Q1, Q2, and Q3 times",
    category="results",
    doc_llm=(
        "One row per driver per qualifying session with Q1/Q2/Q3 lap times as published and as "
        "exact seconds. Pass round := N for one event or omit it for the season. Qualifying "
        "position is not always the starting grid (penalties); use race_results().grid for that."
    ),
    doc_md="Qualifying results. Knockout-phase times are null for phases a driver did not reach.",
    examples=[
        Example(
            "Pole sitters in 2024.",
            "SELECT round, race_name, driver_name, q3 FROM f1.main.qualifying_results(2024) "
            "WHERE position = 1 ORDER BY round",
        )
    ],
    estimate=480,
    maximum=1_000,
    source=SOURCE,
)

LapTimesFunction = table_function(
    name="lap_times",
    args=LapArgs,
    schema=LAP_TIMES_SCHEMA,
    fetch=lambda args: _fetch(
        f"{args.season}/{args.round}/drivers/{args.driver_id}/laps"
        if args.driver_id
        else f"{args.season}/{args.round}/laps",
        "Races",
        flatten_lap_times,
        season=args.season,
    ),
    title="F1 Race Lap Times",
    description="Lap-by-lap times and running positions for one Grand Prix (1996 onwards)",
    category="timing",
    doc_llm=(
        "One row per driver per lap of one race, with running position and lap time. Requires "
        "season and round; pass driver_id := '...' to fetch a single driver cheaply. A full race "
        "is roughly 1,000-1,400 rows fetched over 10-15 upstream pages."
    ),
    doc_md=(
        "Race lap times from 1996 onwards. Filtering by `driver_id` is pushed to the API and "
        "is much cheaper than filtering in SQL."
    ),
    examples=[
        Example(
            "Max Verstappen's laps in the 2024 Chinese Grand Prix.",
            "SELECT lap, position, lap_time FROM f1.main.lap_times(2024, 5, driver_id := 'max_verstappen') "
            "ORDER BY lap",
        ),
        STINT_PACE,
    ],
    estimate=1_100,
    maximum=2_000,
    source=SOURCE,
)

PitStopsFunction = table_function(
    name="pit_stops",
    args=RaceArgs,
    schema=PIT_STOPS_SCHEMA,
    fetch=lambda args: _fetch(
        f"{args.season}/{args.round}/pitstops", "Races", flatten_pit_stops, season=args.season
    ),
    title="F1 Pit Stops",
    description="Pit stops for one Grand Prix (2011 onwards)",
    category="timing",
    doc_llm=(
        "One row per pit stop in one race: driver, stop number, lap, and pit-lane duration. "
        "Durations are entry-to-exit pit-lane times, not stationary times; red-flag stops can "
        "be many minutes long."
    ),
    doc_md="Pit stops from 2011 onwards. `duration_seconds` is an exact decimal.",
    examples=[
        Example(
            "Fastest pit-lane times in the 2024 Chinese Grand Prix.",
            "SELECT driver_id, lap, duration_seconds FROM f1.main.pit_stops(2024, 5) "
            "ORDER BY duration_seconds LIMIT 5",
        )
    ],
    estimate=40,
    maximum=150,
    source=SOURCE,
)

DriversFunction = table_function(
    name="drivers",
    args=OptionalSeasonArgs,
    schema=DRIVERS_SCHEMA,
    fetch=lambda args: _fetch(
        f"{args.season}/drivers" if args.season else "drivers",
        "Drivers",
        flatten_drivers,
        season=args.season or FIRST_SEASON,
    ),
    title="F1 Drivers",
    description="Drivers who entered a season, or every World Championship driver",
    category="reference",
    doc_llm=(
        "One row per driver with identifier, code, permanent number, name, date of birth, and "
        "nationality. Use it to find driver_id values for other functions. Without a season it "
        "returns all ~880 drivers since 1950 (several upstream pages)."
    ),
    doc_md="Driver reference data. `driver_id` is the key used by every other Jolpica function.",
    examples=[
        Example(
            "The 2024 grid.",
            "SELECT driver_id, driver_code, driver_name, nationality FROM f1.main.drivers(season := 2024) "
            "ORDER BY family_name",
        )
    ],
    estimate=25,
    maximum=1_000,
    source=SOURCE,
)

ConstructorsFunction = table_function(
    name="constructors",
    args=OptionalSeasonArgs,
    schema=CONSTRUCTORS_SCHEMA,
    fetch=lambda args: _fetch(
        f"{args.season}/constructors" if args.season else "constructors",
        "Constructors",
        flatten_constructors,
        season=args.season or FIRST_SEASON,
    ),
    title="F1 Constructors",
    description="Constructors that entered a season, or every constructor since 1950",
    category="reference",
    doc_llm="One row per constructor (team) with identifier, name, and nationality.",
    doc_md="Constructor reference data keyed by `constructor_id`.",
    examples=[
        Example(
            "The 2024 constructors.",
            "SELECT constructor_id, constructor_name, nationality FROM f1.main.constructors(season := 2024)",
        )
    ],
    estimate=10,
    maximum=300,
    source=SOURCE,
)

CircuitsFunction = table_function(
    name="circuits",
    args=OptionalSeasonArgs,
    schema=CIRCUITS_SCHEMA,
    fetch=lambda args: _fetch(
        f"{args.season}/circuits" if args.season else "circuits",
        "Circuits",
        flatten_circuits,
        season=args.season or FIRST_SEASON,
    ),
    title="F1 Circuits",
    description="Circuits used in a season, or every World Championship circuit",
    category="reference",
    doc_llm="One row per circuit with identifier, name, locality, country, and coordinates.",
    doc_md="Circuit reference data keyed by `circuit_id`, with decimal-degree coordinates.",
    examples=[
        Example(
            "Circuits on the 2024 calendar by country.",
            "SELECT circuit_name, locality, country FROM f1.main.circuits(season := 2024) ORDER BY country",
        )
    ],
    estimate=24,
    maximum=100,
    source=SOURCE,
)

DriverResultsFunction = table_function(
    name="driver_results",
    args=DriverResultsArgs,
    schema=RESULTS_SCHEMA,
    fetch=lambda args: _fetch(
        f"{args.season}/drivers/{args.driver_id}/results"
        if args.season
        else f"drivers/{args.driver_id}/results",
        "Races",
        flatten_results,
        season=args.season,
    ),
    title="F1 Driver Race History",
    description="Every Grand Prix result for one driver, optionally limited to a season",
    category="results",
    doc_llm=(
        "One row per Grand Prix the driver entered, across their career or in one season. Use "
        "it for career wins, podiums, points, or finishing records. Get driver_id from drivers()."
    ),
    doc_md="A driver's race-by-race history with the same columns as `race_results()`.",
    examples=[
        Example(
            "Lewis Hamilton's career wins and podiums.",
            "SELECT count(*) FILTER (WHERE position = 1) AS wins, count(*) FILTER (WHERE position <= 3) "
            "AS podiums FROM f1.main.driver_results('hamilton')",
        )
    ],
    estimate=200,
    maximum=500,
    source=SOURCE,
)

CURRENT_FUNCTIONS = [
    CurrentDriverStandingsFunction,
    CurrentConstructorStandingsFunction,
    CurrentScheduleFunction,
    LastRaceResultsFunction,
    SeasonsFunction,
]

FUNCTIONS = [
    *CURRENT_FUNCTIONS,
    ScheduleFunction,
    DriverStandingsFunction,
    ConstructorStandingsFunction,
    RaceResultsFunction,
    SprintResultsFunction,
    QualifyingResultsFunction,
    LapTimesFunction,
    PitStopsFunction,
    DriversFunction,
    ConstructorsFunction,
    CircuitsFunction,
    DriverResultsFunction,
]
