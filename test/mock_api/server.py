"""Serve the recorded upstream fixtures over HTTP for the SQL tests.

``ci/run-integration.sh`` starts this server, points the worker's base-URL
environment variables at it, and runs ``test/sql`` through DuckDB, so the
suite is hermetic. Recorded Jolpica-F1 responses are served under /jolpica
and OpenF1 under /openf1. Prints ``PORT:<n>`` once listening.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from fixture_routes import resolve  # noqa: E402


class _FixtureHandler(BaseHTTPRequestHandler):
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


def main() -> None:
    """Serve until killed."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    print(f"PORT:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
