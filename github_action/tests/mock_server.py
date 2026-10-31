"""Loopback fixture for exercising action.yml on a GitHub-hosted runner."""

from __future__ import annotations

import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            uuid.UUID(self.headers.get("Idempotency-Key", ""))
            length = int(self.headers.get("Content-Length", "0"))
            task = json.loads(self.rfile.read(length))
            valid = (
                self.path == "/v1/runs"
                and self.headers.get("X-API-Key") == "ado_mock_key"
                and self.headers.get("X-Provider") == "openai"
                and self.headers.get("X-Provider-Key") == "mock_provider_key"
                and task["subtasks"][0]["description"] == "Test the Action."
            )
        except (ValueError, KeyError, IndexError, TypeError):
            valid = False
        self.respond(201 if valid else 400, {"run_id": "mock-run", "status": "QUEUED"})

    def do_GET(self) -> None:
        if (self.headers.get("X-API-Key") != "ado_mock_key"
                or any(key.lower().startswith("x-provider") for key in self.headers)):
            self.respond(400, {})
        elif self.path == "/v1/runs/mock-run":
            self.respond(200, {"run_id": "mock-run", "status": "SUCCEEDED"})
        elif self.path == "/v1/runs/mock-run/evidence":
            self.respond(200, {"run_id": "mock-run", "checks": [], "verification_status": "PASSED"})
        else:
            self.respond(404, {})

    def log_message(self, *_args: object) -> None:
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Path(sys.argv[1]).write_text(f"http://127.0.0.1:{server.server_port}", encoding="utf-8")
    server.serve_forever()
