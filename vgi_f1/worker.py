"""VGI worker exposing Formula 1 results, standings, and session timing as a SQL catalog."""

from __future__ import annotations

import json
import os
import sys

from vgi import Worker
from vgi.catalog import Catalog, ConstraintInfo, Schema, Table, constraint_record

from vgi_f1.ergast import (
    FUNCTIONS as ERGAST_FUNCTIONS,
)
from vgi_f1.ergast import (
    CurrentConstructorStandingsFunction,
    CurrentDriverStandingsFunction,
    CurrentScheduleFunction,
    LastRaceResultsFunction,
    SeasonsFunction,
)
from vgi_f1.examples import COMPOSED_EXAMPLES, STANDINGS_WITH_LAST_RACE
from vgi_f1.functions import Example
from vgi_f1.meta import column_comments
from vgi_f1.openf1 import FUNCTIONS as OPENF1_FUNCTIONS
from vgi_f1.schemas import (
    CONSTRUCTOR_STANDINGS_SCHEMA,
    DRIVER_STANDINGS_SCHEMA,
    RESULTS_SCHEMA,
    SCHEDULE_SCHEMA,
    SEASONS_SCHEMA,
)

SOURCE_URL = "https://github.com/Query-farm/vgi-f1"


def _examples(*examples: tuple[str, str] | Example) -> str:
    pairs = [(e.description, e.sql) if isinstance(e, Example) else e for e in examples]
    return json.dumps([{"description": description, "sql": sql} for description, sql in pairs])


_DRIVER_STANDINGS_EXAMPLES: tuple[tuple[str, str] | Example, ...] = (
    (
        "The current championship top ten.",
        "SELECT position, driver_name, constructor_name, points, wins "
        "FROM f1.main.current_driver_standings ORDER BY position LIMIT 10",
    ),
    (
        "Points gap from each driver to the leader.",
        "SELECT driver_name, points, max(points) OVER () - points AS gap_to_leader "
        "FROM f1.main.current_driver_standings ORDER BY position",
    ),
    STANDINGS_WITH_LAST_RACE,
)


_DRIVER_STANDINGS_TAGS = {
    "provider": "jolpica-f1",
    "vgi.category": "standings",
    "vgi.title": "F1 Drivers' Standings",
    "vgi.keywords": json.dumps(["drivers' championship", "standings", "points", "title race", "wins"]),
    "vgi.doc_llm": (
        "The current season's drivers' championship after the latest round, one row per driver. "
        "Start here for who leads the title race, points gaps, and wins this season. For another "
        "season or the table after a specific round, call driver_standings()."
    ),
    "vgi.doc_md": (
        "The current Formula 1 drivers' championship as an ordinary read-only table, refreshed "
        "from Jolpica-F1 at most every ten minutes. Points are exact decimals."
    ),
    "vgi.example_queries": _examples(*_DRIVER_STANDINGS_EXAMPLES),
}

_CONSTRUCTOR_STANDINGS_TAGS = {
    "provider": "jolpica-f1",
    "vgi.category": "standings",
    "vgi.title": "F1 Constructors' Standings",
    "vgi.keywords": json.dumps(["constructors' championship", "teams", "standings", "points"]),
    "vgi.doc_llm": (
        "The current season's constructors' (teams') championship, one row per constructor. Use "
        "constructor_standings() for another season or a specific round."
    ),
    "vgi.doc_md": "The current constructors' championship as an ordinary read-only table.",
    "vgi.example_queries": _examples(
        (
            "Current constructors' table.",
            "SELECT position, constructor_name, points, wins "
            "FROM f1.main.current_constructor_standings ORDER BY position",
        ),
    ),
}

_SCHEDULE_TAGS = {
    "provider": "jolpica-f1",
    "vgi.category": "schedule",
    "vgi.title": "F1 Season Calendar",
    "vgi.keywords": json.dumps(["calendar", "schedule", "next race", "sprint", "session times"]),
    "vgi.doc_llm": (
        "Every round of the current season with race date, circuit, country, and UTC session "
        "start times. Use it for the next race (race_date >= current_date) or sprint weekends. "
        "Use schedule() for other seasons."
    ),
    "vgi.doc_md": "The current season calendar. Session starts are UTC timestamps.",
    "vgi.example_queries": _examples(
        (
            "Remaining races this season.",
            "SELECT round, race_name, country, race_start_utc FROM f1.main.current_schedule "
            "WHERE race_date >= current_date ORDER BY round",
        ),
    ),
}

_LAST_RACE_TAGS = {
    "provider": "jolpica-f1",
    "vgi.category": "results",
    "vgi.title": "Last Grand Prix Result",
    "vgi.keywords": json.dumps(["last race", "latest result", "podium", "winner", "classification"]),
    "vgi.doc_llm": (
        "The full classification of the most recently completed Grand Prix, one row per driver: "
        "position, points, grid, laps, status, time, and fastest lap. Use race_results() for any "
        "other race and sprint_results() for sprints."
    ),
    "vgi.doc_md": "The most recent Grand Prix classification as an ordinary read-only table.",
    "vgi.example_queries": _examples(
        (
            "Podium of the latest Grand Prix.",
            "SELECT race_name, position, driver_name, constructor_name, race_time "
            "FROM f1.main.last_race_results WHERE position <= 3 ORDER BY position",
        ),
        (
            "Biggest gainers from grid to finish in the latest race.",
            "SELECT driver_name, grid, position, grid - position AS places_gained "
            "FROM f1.main.last_race_results WHERE classified AND grid > 0 "
            "ORDER BY places_gained DESC LIMIT 5",
        ),
    ),
}

_SEASONS_TAGS = {
    "provider": "jolpica-f1",
    "vgi.category": "reference",
    "vgi.title": "F1 Championship Seasons",
    "vgi.keywords": json.dumps(["seasons", "years", "history", "World Championship"]),
    "vgi.doc_llm": (
        "One row per Formula 1 World Championship season from 1950 to the present, with its "
        "Wikipedia link. Use it to enumerate valid season arguments."
    ),
    "vgi.doc_md": "Every championship season in the Jolpica-F1 archive.",
    "vgi.example_queries": _examples(
        ("Seasons held so far.", "SELECT count(*) AS seasons, max(season) AS latest FROM f1.main.seasons"),
    ),
}

_EXECUTABLE_EXAMPLES = json.dumps(
    [
        {
            "name": "current_driver_standings_are_populated",
            "description": "The current drivers' championship has driver rows with stable identifiers.",
            "sql": (
                "SELECT count(*) > 0 AND count(driver_id) = count(*) AS populated "
                "FROM f1.main.current_driver_standings"
            ),
            "expected_result": [{"populated": True}],
        },
        {
            "name": "championship_points_are_ordered",
            "description": "A higher championship position never has more points than a lower one.",
            "sql": (
                "SELECT bool_and(points <= prev_points) AS ordered FROM ("
                "SELECT points, lag(points) OVER (ORDER BY position) AS prev_points "
                "FROM f1.main.current_driver_standings WHERE position IS NOT NULL) "
                "WHERE prev_points IS NOT NULL"
            ),
            "expected_result": [{"ordered": True}],
        },
        {
            "name": "verstappen_2023_wins",
            "description": "Max Verstappen won 19 Grands Prix in 2023.",
            "sql": (
                "SELECT count(*) AS wins FROM f1.main.race_results(2023) "
                "WHERE position = 1 AND driver_id = 'max_verstappen'"
            ),
            "expected_result": [{"wins": 19}],
        },
    ]
)

_AGENT_TEST_TASKS = json.dumps(
    [
        {
            "name": "current_season_summary",
            "prompt": (
                "Summarize the current Formula 1 season: who leads the drivers' and constructors' "
                "championships, who won the most recent Grand Prix, and how many rounds remain?"
            ),
        },
        {
            "name": "final_2024_champions",
            "prompt": (
                "Who won the 2024 F1 drivers' and constructors' championships, and with how many points?"
            ),
        },
        {
            "name": "wins_by_driver_2024",
            "prompt": (
                "How many Grand Prix wins and how many sprint wins did each driver score in 2024? "
                "Most Grand Prix wins first."
            ),
        },
        {
            "name": "monaco_2024_pole",
            "prompt": (
                "Which round was the 2024 Monaco Grand Prix, who took pole position, and what was "
                "the Q3 time?"
            ),
        },
        {
            "name": "china_2024_verstappen_stops",
            "prompt": (
                "List Max Verstappen's pit stops in the 2024 Chinese Grand Prix (round 5) with lap "
                "and pit-lane time, plus his fastest lap of the race in seconds."
            ),
        },
        {
            "name": "hamilton_wins_through_2024",
            "prompt": "How many Grand Prix did Lewis Hamilton win from his debut through the end of 2024?",
        },
        {
            "name": "field_size_2024",
            "prompt": (
                "How many constructors entered the 2024 season, how many circuits were used, and "
                "how many World Championship seasons had been held up to and including 2024?"
            ),
        },
        {
            "name": "bahrain_2024_verstappen_tyres",
            "prompt": (
                "Which tyre compounds did Max Verstappen use in the 2024 Bahrain Grand Prix race, "
                "and on which laps did each stint start and end?"
            ),
        },
        {
            "name": "bahrain_2024_fastest_lap",
            "prompt": (
                "Who set the fastest lap of the 2024 Bahrain Grand Prix race, on which lap, and "
                "where did that driver finish?"
            ),
        },
        {
            "name": "bahrain_2024_race_story",
            "prompt": (
                "For the 2024 Bahrain Grand Prix race, give the official event name, the number of "
                "flag messages from race control, whether it rained, the number of pit stops, and "
                "the number of team radio clips."
            ),
        },
        {
            "name": "china_2024_podium_pit_stops",
            "prompt": (
                "For the 2024 Chinese Grand Prix (round 5), list the three podium finishers in "
                "finishing order with their finishing position, driver name, number of pit stops, "
                "and total pit-lane time in seconds."
            ),
        },
        {
            "name": "bahrain_2024_least_pit_lane_time_team",
            "prompt": (
                "In the 2024 Bahrain Grand Prix race, which team spent the least combined time in "
                "the pit lane across both of its cars? Return one row: the team name, the team's "
                "total number of pit stops, and the best finishing position of its drivers."
            ),
        },
    ]
)


def _key_constraints(table: str, key: tuple[str, ...]) -> tuple[ConstraintInfo, ...]:
    """Primary-key and NOT NULL records for a read-only table keyed by ``key``."""
    records = [
        constraint_record(
            ["main"],
            table,
            "pk",
            "PRIMARY_KEY",
            [[column] for column in key],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
    ]
    records += [
        constraint_record(
            ["main"],
            table,
            f"{column}_not_null",
            "NOT_NULL",
            [[column]],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
        for column in key
    ]
    return tuple(records)


F1_CATALOG = Catalog(
    name="f1",
    default_schema="main",
    source_url=SOURCE_URL,
    comment=(
        "Read-only Formula 1 results, standings, calendars, and session timing from Jolpica-F1 and OpenF1"
    ),
    tags={
        "provider": "f1",
        "domain": "sports",
        "vgi.title": "Formula 1 Data",
        "vgi.subtitle": "F1 standings, results, calendars, lap times, and session timing as SQL tables.",
        "vgi.source_url": SOURCE_URL,
        "vgi.author": "Query Farm LLC <hello@query.farm>",
        "vgi.copyright": (
            "Worker (c) 2026 Query Farm LLC. Data from Jolpica-F1 and OpenF1, each licensed "
            "CC BY-NC-SA 4.0 (non-commercial). Not affiliated with Formula 1 or the FIA."
        ),
        "vgi.license": "MIT",
        "vgi.support_contact": "https://github.com/Query-farm/vgi-f1/issues",
        "vgi.support_policy_url": "https://github.com/Query-farm/vgi-f1/blob/main/README.md",
        "vgi.keywords": json.dumps(
            ["Formula 1", "F1", "motorsport", "Grand Prix", "standings", "lap times", "telemetry"]
        ),
        "vgi.executable_examples": _EXECUTABLE_EXAMPLES,
        "vgi.agent_test_tasks": _AGENT_TEST_TASKS,
        "vgi.doc_llm": (
            "Read-only Formula 1 data. Jolpica-F1 (the Ergast successor) supplies 1950-present "
            "calendars, race, sprint, and qualifying results, drivers' and constructors' "
            "championships by round, lap times (1996+), pit stops (2011+), and driver, "
            "constructor, and circuit reference data keyed by text ids such as 'hamilton'. "
            "OpenF1 supplies 2023+ session-level timing keyed by session_key and driver_number: "
            "meetings, sessions, entry lists, classifications, laps and sectors, tyre stints, pit "
            "stops, weather, race control messages, and team radio links. Start with the current_* "
            "tables and last_race_results; call sessions() to find a session_key."
        ),
        "vgi.doc_md": (
            "# Formula 1 results, standings, and timing\n\n"
            "Query Formula 1 from SQL. Current tables cover this season's championships, "
            "calendar, and latest result. Parameterized functions reach back to 1950 for "
            "results and standings, and into 2023+ sessions for lap, stint, pit, weather, and "
            "race-control detail.\n\n"
            "## Data model\n\n"
            "Jolpica-F1 functions are keyed by `season`, `round`, and text ids (`driver_id`, "
            "`constructor_id`, `circuit_id`). OpenF1 functions are keyed by `session_key` and car "
            "`driver_number`; use `session_drivers()` to map numbers to names.\n\n"
            "## Licence\n\n"
            "Both sources publish their data under CC BY-NC-SA 4.0: attribute them, do not use the "
            "data commercially, and share derived datasets alike. This worker fetches on demand "
            "and does not rehost data. It is not affiliated with Formula 1 or the FIA."
        ),
    },
    schemas=[
        Schema(
            path=["main"],
            comment="Formula 1 championships, results, calendars, and session timing",
            tags={
                "provider": "f1",
                "domain": "sports",
                "vgi.title": "Formula 1",
                "vgi.keywords": json.dumps(
                    ["F1", "standings", "results", "qualifying", "lap times", "pit stops", "tyres"]
                ),
                "vgi.categories": json.dumps(
                    [
                        {
                            "name": "standings",
                            "title": "Championships",
                            "description": "Drivers' and constructors' championship standings by round.",
                            "keywords": ["standings", "points", "championship", "title"],
                        },
                        {
                            "name": "results",
                            "title": "Results",
                            "description": "Race, sprint, and qualifying classifications.",
                            "keywords": ["results", "winner", "podium", "qualifying", "sprint"],
                        },
                        {
                            "name": "schedule",
                            "title": "Calendar",
                            "description": "Season calendars with UTC session start times.",
                            "keywords": ["calendar", "schedule", "next race"],
                        },
                        {
                            "name": "timing",
                            "title": "Timing",
                            "description": "Lap times, sectors, tyre stints, and pit stops.",
                            "keywords": ["laps", "sectors", "stints", "tyres", "pit stops"],
                        },
                        {
                            "name": "sessions",
                            "title": "Sessions",
                            "description": (
                                "OpenF1 meetings, sessions, entry lists, weather, race control, and "
                                "team radio."
                            ),
                            "keywords": ["sessions", "weather", "race control", "flags", "radio"],
                        },
                        {
                            "name": "reference",
                            "title": "Reference",
                            "description": "Seasons, drivers, constructors, and circuits.",
                            "keywords": ["drivers", "constructors", "teams", "circuits"],
                        },
                    ]
                ),
                "vgi.doc_llm": (
                    "Use current_driver_standings and current_constructor_standings for this "
                    "season's title races, current_schedule for the calendar, and "
                    "last_race_results for the latest Grand Prix. Historical functions take a "
                    "season (and optional round); OpenF1 session functions take a session_key "
                    "from sessions()."
                ),
                "vgi.doc_md": (
                    "## Formula 1 analytical data\n\n"
                    "Rows are explicitly driver-, constructor-, round-, lap-, stint-, stop-, or "
                    "message-grain. Times are exact decimal seconds from Jolpica-F1 and `DOUBLE` "
                    "seconds from OpenF1; published display strings are kept alongside.\n\n"
                    "Start with the `current_*` tables and `last_race_results`. Historical "
                    "functions take `season` (and optionally `round`); OpenF1 session functions "
                    "take a `session_key` found with `sessions()`."
                ),
                "vgi.example_queries": _examples(
                    *(e for e in _DRIVER_STANDINGS_EXAMPLES if e not in COMPOSED_EXAMPLES),
                    *COMPOSED_EXAMPLES,
                ),
            },
            functions=[*ERGAST_FUNCTIONS, *OPENF1_FUNCTIONS],
            tables=[
                Table(
                    name="current_driver_standings",
                    function=CurrentDriverStandingsFunction,
                    comment="Current-season drivers' championship standings, one row per driver",
                    tags=_DRIVER_STANDINGS_TAGS,
                    column_comments=column_comments(DRIVER_STANDINGS_SCHEMA),
                    constraints=_key_constraints("current_driver_standings", ("driver_id",)),
                    cardinality_estimate=22,
                ),
                Table(
                    name="current_constructor_standings",
                    function=CurrentConstructorStandingsFunction,
                    comment="Current-season constructors' championship standings, one row per team",
                    tags=_CONSTRUCTOR_STANDINGS_TAGS,
                    column_comments=column_comments(CONSTRUCTOR_STANDINGS_SCHEMA),
                    constraints=_key_constraints("current_constructor_standings", ("constructor_id",)),
                    cardinality_estimate=11,
                ),
                Table(
                    name="current_schedule",
                    function=CurrentScheduleFunction,
                    comment="Current-season race calendar, one row per round",
                    tags=_SCHEDULE_TAGS,
                    column_comments=column_comments(SCHEDULE_SCHEMA),
                    constraints=_key_constraints("current_schedule", ("round",)),
                    cardinality_estimate=24,
                ),
                Table(
                    name="last_race_results",
                    function=LastRaceResultsFunction,
                    comment="Classification of the most recent Grand Prix, one row per driver",
                    tags=_LAST_RACE_TAGS,
                    column_comments=column_comments(RESULTS_SCHEMA),
                    constraints=_key_constraints("last_race_results", ("driver_id",)),
                    cardinality_estimate=20,
                ),
                Table(
                    name="seasons",
                    function=SeasonsFunction,
                    comment="Every Formula 1 World Championship season since 1950",
                    tags=_SEASONS_TAGS,
                    column_comments=column_comments(SEASONS_SCHEMA),
                    constraints=_key_constraints("seasons", ("season",)),
                    cardinality_estimate=77,
                ),
            ],
        )
    ],
)


class F1Worker(Worker):
    """Worker process hosting the read-only Formula 1 catalog."""

    catalog = F1_CATALOG


def main() -> None:
    """Run over stdio by default, or HTTP when VGI's ``--http`` flag is supplied."""
    F1Worker.main()


def main_http() -> None:
    """Run HTTP with production-safe configuration requirements."""
    if not os.environ.get("VGI_SIGNING_KEY"):
        raise SystemExit(
            "VGI_SIGNING_KEY is required for HTTP mode so state remains valid across restarts and replicas"
        )
    auth_configured = bool(os.environ.get("VGI_BEARER_TOKENS") or os.environ.get("VGI_JWT_ISSUER"))
    auth_configured = auth_configured or os.environ.get("VGI_PROXY_PROOF_MODE", "").lower() == "require"
    if not auth_configured and os.environ.get("VGI_ALLOW_ANONYMOUS") != "1":
        raise SystemExit(
            "HTTP authentication is required; configure bearer/JWT/proxy proof, or explicitly set "
            "VGI_ALLOW_ANONYMOUS=1 for an intentionally public deployment"
        )
    argv = sys.argv[1:]
    if "--http" not in argv:
        argv = ["--http", *argv]
    if "--describe" not in argv and "--no-describe" not in argv:
        argv = ["--no-describe", *argv]
    if not any(value == "--cors-origins" or value.startswith("--cors-origins=") for value in argv):
        argv = ["--cors-origins", "", *argv]
    sys.argv = [sys.argv[0], *argv]
    F1Worker.main()
