"""Hermetic end-to-end coverage through Haybarn and the VGI transport."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from fixture_routes import resolve

from vgi_f1.examples import COMPOSED_EXAMPLES


class _FixtureHandler(BaseHTTPRequestHandler):
    """Serve recorded Jolpica-F1 responses under /jolpica and OpenF1 under /openf1."""

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        source, _, rest = parsed.path.lstrip("/").partition("/")
        if source not in {"jolpica", "openf1"}:
            self.send_error(404)
            return
        status, payload = resolve(source, rest, dict(parse_qsl(parsed.query)))
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if source == "jolpica":
            self.send_header("Cache-Control", "max-age=600")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _run_haybarn(sql: str) -> str:
    """Run ``sql`` in Haybarn with the worker attached as ``f1`` against the fixture server."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    project = Path(__file__).resolve().parent.parent
    location = f"uv run --project {project} vgi-f1"
    attach = f"INSTALL vgi FROM community; LOAD vgi; ATTACH 'f1' (TYPE vgi, LOCATION '{location}'); "
    env = {
        **os.environ,
        "F1_JOLPICA_BASE_URL": f"http://127.0.0.1:{server.server_port}/jolpica",
        "F1_OPENF1_BASE_URL": f"http://127.0.0.1:{server.server_port}/openf1",
    }
    try:
        result = subprocess.run(
            ["uvx", "haybarn-cli", ":memory:", "-csv", "-c", attach + sql],
            cwd=project,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return result.stdout


def test_haybarn_attaches_and_queries_every_current_table() -> None:
    stdout = _run_haybarn(
        "SELECT "
        "(SELECT count(*) FROM f1.main.current_driver_standings) AS drivers, "
        "(SELECT count(*) FROM f1.main.current_constructor_standings) AS constructors, "
        "(SELECT count(*) FROM f1.main.current_schedule) AS rounds, "
        "(SELECT count(*) FROM f1.main.last_race_results) AS results, "
        "(SELECT count(*) FROM f1.main.seasons) AS seasons, "
        "(SELECT driver_name FROM f1.main.current_driver_standings WHERE position = 1) AS leader, "
        "(SELECT count(*) FROM f1.main.race_results(2024) WHERE position = 1) AS winners, "
        "(SELECT count(*) FROM f1.main.lap_times(2024, 5, driver_id := 'max_verstappen')) AS laps, "
        "(SELECT max(points) FROM f1.main.session_result(9472)) AS top_points, "
        "(SELECT count(*) FROM f1.main.session_stints(1)) AS missing_session;"
    )
    assert (
        "drivers,constructors,rounds,results,seasons,leader,winners,laps,top_points,missing_session" in stdout
    )
    assert "5,4,3,5,3,Andrea Kimi Antonelli,2,6,26.00,0" in stdout


def test_haybarn_runs_every_composed_example() -> None:
    # The trimmed fixtures only partly overlap (the 2024 sprint and results fixtures share
    # no round; the 9472 stints and result fixtures share no car), so those two examples
    # bind and run but return just their header; the others return real rows.
    stdout = _run_haybarn("".join(f"{example.sql};" for example in COMPOSED_EXAMPLES))
    assert stdout.splitlines() == [
        "position,driver_name,points,last_race_finish,last_race_points",
        "1,Andrea Kimi Antonelli,390.00,5,10.00",
        "2,Max Verstappen,279.00,2,18.00",
        "3,George Russell,262.00,4,12.00",
        "4,Lewis Hamilton,261.00,NULL,0.00",
        "5,Charles Leclerc,249.00,NULL,0.00",
        "round,race_name,sprint_winner,grand_prix_winner,won_both",
        "stint,first_lap,last_lap,best_lap_seconds,median_lap_seconds",
        "1,1,2,100.103,101.328",
        "position,name_acronym,team_name,stints,strategy",
    ]
