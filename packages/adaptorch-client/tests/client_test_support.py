from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TypeAlias

import pytest

JSONValue: TypeAlias = (
    bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"] | None
)
JSONMapping: TypeAlias = dict[str, JSONValue]


@dataclass(frozen=True, slots=True)
class CapturedRequest:
    method: str
    path: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class ResponsePlan:
    status: int
    body: bytes
    headers: Mapping[str, str]


class LocalAPIServer:
    def __init__(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                owner._handle(self)

            def do_POST(self) -> None:  # noqa: N802
                owner._handle(self)

            def log_message(self, format: str, *args: JSONValue) -> None:
                return

        self.requests: list[CapturedRequest] = []
        self._responses: list[ResponsePlan] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def enqueue_json(self, payload: JSONMapping, *, status: int = 200) -> None:
        self.enqueue_raw(
            json.dumps(payload, separators=(",", ":")).encode(),
            status=status,
            headers={"Content-Type": "application/json"},
        )

    def enqueue_raw(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._responses.append(ResponsePlan(status, body, headers or {}))

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length", "0"))
        self.requests.append(
            CapturedRequest(
                method=handler.command,
                path=handler.path,
                headers=dict(handler.headers.items()),
                body=handler.rfile.read(length),
            )
        )
        response = self._responses.pop(0) if self._responses else ResponsePlan(500, b"{}", {})
        response_headers = {"Content-Length": str(len(response.body)), **response.headers}
        handler.send_response(response.status)
        for name, value in response_headers.items():
            handler.send_header(name, value)
        handler.end_headers()
        try:
            handler.wfile.write(response.body)
        except BrokenPipeError:
            return


def make_run_payload(status: str = "queued") -> JSONMapping:
    """Return a fresh contract-shaped direct Run payload."""
    return {
        "run_id": "run-1",
        "kind": "orchestration",
        "status": status,
        "phase": "accepted",
        "created_at": "2026-07-01T12:00:00Z",
        "policy_version": "2026-07-01",
        "links": {"self": "/v1/runs/run-1"},
    }


@pytest.fixture
def local_api() -> Iterator[LocalAPIServer]:
    server = LocalAPIServer()
    server.start()
    try:
        yield server
    finally:
        server.close()
