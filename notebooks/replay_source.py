"""Serve the two hash-verified, complete Jolpica responses on a local ephemeral port."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class ReplaySource:
    """A strict local replay of the documented request paths; no remote fallback."""

    def __init__(self, directory: Path) -> None:
        self.manifest = json.loads((directory / "manifest.json").read_text())
        self.requests: list[str] = []
        bodies = {}
        for entry in self.manifest["entries"]:
            body = (directory / entry["filename"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != entry["sha256"]:
                raise ValueError(f"Recorded response checksum mismatch: {entry['filename']}")
            bodies["/" + entry["path"]] = body
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                requests.append(self.path)
                if (
                    parsed.path not in bodies
                    or query.get("offset", ["0"]) != ["0"]
                    or query.get("limit", ["100"]) != ["100"]
                    or set(query) - {"limit", "offset"}
                ):
                    self.send_error(400, "Request outside the complete recorded coverage")
                    return
                body = bodies[parsed.path]
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
        """Close this notebook's server and join its thread."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
