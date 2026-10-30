"""The MCP connector reuses read connections and never re-sends a write."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from adaptorch.n8n_connector import (
    ControlPlaneProviderCredential,
    N8nConnectorConfig,
    N8nConnectorError,
)

from adaptorch_client import keepalive
from adaptorch_mcp_legacy.control_plane_backend import SafeControlPlaneConnector

RUN = {"run_id": "run-1", "status": "QUEUED"}


@dataclass
class Origin:
    exchanges: list[tuple[int, str, str]] = field(default_factory=list)
    connections: int = 0
    delay_seconds: float = 0.0
    drop_after_response: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    server: ThreadingHTTPServer | None = None

    @property
    def base_url(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_port}"


@pytest.fixture
def origin() -> Iterator[Origin]:
    state = Origin()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self) -> None:
            super().setup()
            with state.lock:
                state.connections += 1
                self.number = state.connections

        def _serve(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            with state.lock:
                state.exchanges.append((self.number, self.command, self.path))
            if state.delay_seconds:
                time.sleep(state.delay_seconds)
            body = json.dumps(RUN).encode()
            self.send_response(201 if self.command == "POST" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            if state.drop_after_response:
                self.close_connection = True

        do_GET = _serve  # noqa: N815
        do_POST = _serve  # noqa: N815

        def log_message(self, format: str, *args: object) -> None:
            return

    state.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.server.daemon_threads = True
    thread = threading.Thread(
        target=state.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield state
    finally:
        state.server.shutdown()
        state.server.server_close()
        thread.join(timeout=2)


def _connector(origin: Origin, *, timeout: float = 2.0) -> SafeControlPlaneConnector:
    return SafeControlPlaneConnector(
        N8nConnectorConfig(
            base_url=origin.base_url,
            api_token="ado_synthetic-tenant",
            timeout_seconds=timeout,
            connector_source="mcp",
            provider_credential=ControlPlaneProviderCredential("openai", "fixture", "byok"),
        )
    )


def test_status_reads_share_one_connection(origin: Origin) -> None:
    connector = _connector(origin)
    try:
        for _ in range(4):
            assert connector.get_run("run-1")["run_id"] == "run-1"
    finally:
        connector.close()

    assert [number for number, _method, _path in origin.exchanges] == [1, 1, 1, 1]
    assert origin.connections == 1


def test_submission_opens_its_own_connection_and_is_sent_once(origin: Origin) -> None:
    connector = _connector(origin)
    try:
        connector.get_run("run-1")
        connector.run_task(payload={"subtasks": [{"id": "a", "description": "fixture"}]})
        connector.get_run("run-1")
    finally:
        connector.close()

    assert [(number, method) for number, method, _path in origin.exchanges] == [
        (1, "GET"),
        (2, "POST"),
        (2, "GET"),
    ]


def test_read_on_a_closed_idle_connection_is_written_once_more(
    origin: Origin, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin.drop_after_response = True
    monkeypatch.setattr(keepalive, "_dropped", lambda _connection: False)
    connector = _connector(origin)
    try:
        connector.get_run("run-1")
        time.sleep(0.05)
        assert connector.get_run("run-1")["run_id"] == "run-1"
    finally:
        connector.close()

    assert [method for _number, method, _path in origin.exchanges] == ["GET", "GET"]
    assert origin.connections == 2


def test_timed_out_submission_is_not_resent(origin: Origin) -> None:
    origin.delay_seconds = 0.4
    connector = _connector(origin, timeout=0.1)
    try:
        with pytest.raises(N8nConnectorError):
            connector.run_task(payload={"subtasks": [{"id": "a", "description": "fixture"}]})
    finally:
        connector.close()
    time.sleep(0.5)

    assert [method for _number, method, _path in origin.exchanges] == ["POST"]


def test_connectors_do_not_share_pools(origin: Origin) -> None:
    first, second = _connector(origin), _connector(origin)
    try:
        first.get_run("run-1")
        second.get_run("run-1")
        first.get_run("run-1")
    finally:
        first.close()
        second.close()

    assert [number for number, _method, _path in origin.exchanges] == [1, 2, 1]
