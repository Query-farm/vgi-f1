"""Tests for the SQL-facing catalog shape."""

import json

from vgi_f1 import ergast
from vgi_f1.worker import F1_CATALOG


def test_catalog_surface() -> None:
    schema = F1_CATALOG.schemas[0]
    assert F1_CATALOG.name == "f1"
    assert schema.path == ["main"]
    assert {function.Meta.name for function in schema.functions} == {
        "all_current_driver_standings",
        "all_current_constructor_standings",
        "all_current_schedule",
        "all_last_race_results",
        "all_seasons",
        "schedule",
        "driver_standings",
        "constructor_standings",
        "race_results",
        "sprint_results",
        "qualifying_results",
        "lap_times",
        "pit_stops",
        "drivers",
        "constructors",
        "circuits",
        "driver_results",
        "meetings",
        "sessions",
        "session_drivers",
        "session_result",
        "session_laps",
        "session_stints",
        "session_pits",
        "session_weather",
        "race_control",
        "team_radio",
    }
    assert {table.name: table.function for table in schema.tables} == {
        "current_driver_standings": ergast.CurrentDriverStandingsFunction,
        "current_constructor_standings": ergast.CurrentConstructorStandingsFunction,
        "current_schedule": ergast.CurrentScheduleFunction,
        "last_race_results": ergast.LastRaceResultsFunction,
        "seasons": ergast.SeasonsFunction,
    }


def _key_of(table, kind: str) -> list[tuple[str, ...]]:
    return [
        tuple(name for path in record.definition.column_paths for name in path)
        for record in table.constraints
        if record.definition.kind == kind
    ]


def test_table_keys() -> None:
    keys = {table.name: _key_of(table, "PRIMARY_KEY") for table in F1_CATALOG.schemas[0].tables}
    assert keys == {
        "current_driver_standings": [("driver_id",)],
        "current_constructor_standings": [("constructor_id",)],
        "current_schedule": [("round",)],
        "last_race_results": [("driver_id",)],
        "seasons": [("season",)],
    }
    for table in F1_CATALOG.schemas[0].tables:
        assert _key_of(table, "NOT_NULL") == _key_of(table, "PRIMARY_KEY")


def test_every_table_column_is_commented() -> None:
    for table in F1_CATALOG.schemas[0].tables:
        schema = table.function.FIXED_SCHEMA
        assert set(table.column_comments) == set(schema.names), table.name


def test_discovery_tags_are_present_and_machine_readable() -> None:
    for tags in [
        F1_CATALOG.tags,
        F1_CATALOG.schemas[0].tags,
        *(t.tags for t in F1_CATALOG.schemas[0].tables),
    ]:
        assert tags["vgi.title"]
        assert tags["vgi.doc_llm"]
        assert tags["vgi.doc_md"]
        assert json.loads(tags["vgi.keywords"])
        examples = json.loads(tags["vgi.example_queries"]) if "vgi.example_queries" in tags else []
        assert all(example["sql"].lstrip().upper().startswith(("SELECT", "WITH")) for example in examples)
    for function in F1_CATALOG.schemas[0].functions:
        tags = function.Meta.tags
        assert tags["vgi.title"] and tags["vgi.doc_llm"] and tags["vgi.doc_md"]
        assert json.loads(tags["vgi.result_columns_schema"])
        assert json.loads(tags["vgi.example_queries"])
        assert function.Meta.examples


def test_catalog_discovery_contract_is_public_and_machine_readable() -> None:
    examples = json.loads(F1_CATALOG.tags["vgi.executable_examples"])
    tasks = json.loads(F1_CATALOG.tags["vgi.agent_test_tasks"])

    assert examples
    assert all({"name", "description", "sql", "expected_result"} <= example.keys() for example in examples)
    assert 6 <= len(tasks) <= 12
    assert all(set(task) == {"name", "prompt"} for task in tasks)
    assert len({task["name"] for task in tasks}) == len(tasks)


def test_licence_and_affiliation_are_declared() -> None:
    assert "CC BY-NC-SA 4.0" in F1_CATALOG.tags["vgi.copyright"]
    assert "Not affiliated" in F1_CATALOG.tags["vgi.copyright"]
    assert F1_CATALOG.tags["vgi.license"] == "MIT"
