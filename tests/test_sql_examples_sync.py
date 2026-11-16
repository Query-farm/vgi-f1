"""test/sql/f1.test runs every composed example verbatim; keep the copies in sync."""

from __future__ import annotations

from pathlib import Path

from vgi_f1.examples import COMPOSED_EXAMPLES

SQL_TEST = Path(__file__).resolve().parent.parent / "test" / "sql" / "f1.test"


def test_sql_suite_runs_every_composed_example() -> None:
    lines = SQL_TEST.read_text().splitlines()
    for example in COMPOSED_EXAMPLES:
        assert f"{example.sql};" in lines, example.description
