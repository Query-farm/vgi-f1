"""The private grader sidecar must match the public task list."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from vgi_f1.worker import F1_CATALOG

SIDECAR = Path(__file__).resolve().parent.parent / "vgi-agent-tests.yaml"


def test_sidecar_grades_every_public_task() -> None:
    public = [task["name"] for task in json.loads(F1_CATALOG.tags["vgi.agent_test_tasks"])]
    graders = yaml.safe_load(SIDECAR.read_text())["tasks"]
    assert [task["name"] for task in graders] == public
    for task in graders:
        assert task.get("reference_sql") or task.get("check_sql"), task["name"]
        assert task.get("success_criteria"), task["name"]
        # Live current-season data changes after every race: never exact-compare it.
        if "current_" in (task.get("reference_sql") or "") or "last_race" in (
            task.get("reference_sql") or ""
        ):
            raise AssertionError(f"{task['name']} exact-compares live data")
