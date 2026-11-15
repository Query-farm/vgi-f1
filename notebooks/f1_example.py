"""Hash-verified response replay and scoped source selection for F1 examples."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from replay_source import ReplaySource

ROOT = Path(__file__).resolve().parent
OFFICIAL = {
    "F1_JOLPICA_BASE_URL": "https://api.jolpi.ca/ergast/f1",
    "F1_OPENF1_BASE_URL": "https://api.openf1.org/v1",
}


def request_key(path: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Compare complete request parameters without depending on query order."""
    parsed = urlsplit(path)
    return parsed.path, tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True)))


class PackedReplay:
    """Serve only exact recorded requests; never forward or substitute responses."""

    def __init__(self, scenario: str) -> None:
        payload = (ROOT / "recordings" / f"{scenario}.json.gz").read_bytes()
        self.manifest = json.loads(gzip.decompress(payload))
        self.requests: list[str] = []
        bodies = {}
        for entry in self.manifest["entries"]:
            body = base64.b64decode(entry["body_base64"], validate=True)
            if hashlib.sha256(body).hexdigest() != entry["sha256"]:
                raise ValueError("Recorded response checksum mismatch")
            key = request_key(entry["request"])
            if key in bodies:
                raise ValueError("Duplicate recorded request")
            bodies[key] = body
        self.expected = Counter(bodies.keys())
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                requests.append(self.path)
                body = bodies.get(request_key(self.path))
                if body is None:
                    self.send_error(400, "Request outside recorded coverage")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        """Release this loopback service."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class Source:
    """Select explicit recorded or official reads and restore caller settings."""

    def __init__(self, mode: str, scenario: str) -> None:
        if mode not in {"replay", "live"} or scenario not in {"laps", "weekend", "session"}:
            raise ValueError("Choose replay/live and a documented notebook scenario")
        self.mode = mode
        self.scenario = scenario
        self.previous = {key: os.environ.get(key) for key in OFFICIAL}
        self.replay = None
        if mode == "replay":
            self.replay = ReplaySource(ROOT / "fixtures") if scenario == "laps" else PackedReplay(scenario)
        if scenario == "laps":
            self.manifest = json.loads((ROOT / "fixtures/manifest.json").read_text())
        else:
            self.manifest = json.loads(
                gzip.decompress((ROOT / "recordings" / f"{scenario}.json.gz").read_bytes())
            )
        for key, value in OFFICIAL.items():
            os.environ[key] = value
        if self.replay:
            key = "F1_OPENF1_BASE_URL" if scenario == "session" else "F1_JOLPICA_BASE_URL"
            os.environ[key] = self.replay.url

    @property
    def requests(self) -> list[str]:
        """Recorded service requests; empty for uninstrumented public live mode."""
        return self.replay.requests if self.replay else []

    def capture_bounds(self) -> tuple[str, str]:
        """Original acquisition interval, distinct from notebook execution time."""
        begin, end = (
            ("retrieval_start_utc", "retrieval_end_utc")
            if self.scenario == "laps"
            else ("capture_started_utc", "capture_finished_utc")
        )
        return min(e[begin] for e in self.manifest["entries"]), max(e[end] for e in self.manifest["entries"])

    def audit(self) -> dict:
        """Require every recorded request exactly once after materialization."""
        if self.replay:
            if self.scenario == "laps":
                expected = Counter(
                    request_key("/" + e["path"] + "?limit=100&offset=0") for e in self.manifest["entries"]
                )
            else:
                expected = self.replay.expected
            actual = Counter(request_key(path) for path in self.requests)
            if actual != expected:
                raise AssertionError("Replay request population differs from complete recorded coverage")
            return {"mode": "replay", "requests": len(self.requests), "exact_recorded_requests": True}
        return {"mode": "live", "requests": None, "exact_recorded_requests": None}

    def close(self) -> None:
        """Close the local server and restore inherited source URLs."""
        if self.replay:
            self.replay.close()
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
