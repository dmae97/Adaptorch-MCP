"""Persistent connections: reads reuse a socket, writes never do, nothing is sent twice."""

from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

import pytest
from client_test_support import make_run_payload

from adaptorch_client import AdaptOrchAPIError, AdaptOrchClient, ClientConfig, keepalive
from adaptorch_client.transport import HTTPTransport, RequestSpec, _NoRedirectHandler

REQUEST_ID = "11111111-1111-4111-8111-111111111111"


@dataclass
class _Exchange:
    connection: int
    method: str
    path: str


@dataclass
class KeepAliveServer:
    """HTTP/1.1 test origin that records which TCP connection carried each request."""

    delay_seconds: float = 0.0
    drop_after_response: bool = False
    exchanges: list[_Exchange] = field(default_factory=list)
    connections: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    body: Callable[[str], bytes] = lambda path: json.dumps(make_run_payload()).encode()

    def start(self, wrap: Callable[[ThreadingHTTPServer], None] | None = None) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self) -> None:
                super().setup()
                with owner._lock:
                    owner.connections += 1
                    self.connection_number = owner.connections

            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                with owner._lock:
                    owner.exchanges.append(
                        _Exchange(self.connection_number, self.command, self.path)
                    )
                if owner.delay_seconds:
                    time.sleep(owner.delay_seconds)
                body = owner.body(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    return
                if owner.drop_after_response:
                    # Advertise keep-alive, then close: the race a pooled client must survive.
                    self.close_connection = True

            do_GET = _serve  # noqa: N815
            do_POST = _serve  # noqa: N815
            do_PUT = _serve  # noqa: N815

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        if wrap is not None:
            wrap(self._server)
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()

    @property
    def port(self) -> int:
        assert self._server is not None
        return self._server.server_port

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        assert self._server is not None and self._thread is not None
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


@pytest.fixture
def origin() -> Iterator[KeepAliveServer]:
    server = KeepAliveServer()
    server.start()
    try:
        yield server
    finally:
        server.close()


def _client(api_url: str, timeout: float = 2.0) -> AdaptOrchClient:
    config = ClientConfig(api_url=api_url, api_key="ado_test", timeout_seconds=timeout)
    return AdaptOrchClient(config)


def test_reads_reuse_one_connection(origin: KeepAliveServer) -> None:
    with _client(origin.api_url) as client:
        for _ in range(5):
            assert client.get_run("run-1").run_id == "run-1"

    assert [exchange.connection for exchange in origin.exchanges] == [1] * 5
    assert origin.connections == 1


def test_submission_and_cancel_never_take_an_idle_connection(origin: KeepAliveServer) -> None:
    with _client(origin.api_url) as client:
        client.get_run("run-1")
        client.submit_run({"goal": "x"}, REQUEST_ID)
        client.cancel_run("run-1")
        client.get_run("run-1")

    methods = [(exchange.method, exchange.connection) for exchange in origin.exchanges]
    assert methods[0] == ("GET", 1)
    assert methods[1] == ("POST", 2)
    assert methods[2] == ("PUT", 3)
    # The connection a completed write used is a valid idle connection for the next read.
    assert methods[3] == ("GET", 3)


def test_read_on_a_connection_the_server_closed_is_sent_once_more(
    origin: KeepAliveServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin.drop_after_response = True
    # Defeat the idle probe so the request really meets a closed socket.
    monkeypatch.setattr(keepalive, "_dropped", lambda _connection: False)
    with _client(origin.api_url) as client:
        client.get_run("run-1")
        time.sleep(0.05)
        assert client.get_run("run-1").run_id == "run-1"

    assert [exchange.method for exchange in origin.exchanges] == ["GET", "GET"]
    assert origin.connections == 2


def test_idle_probe_discards_a_closed_connection_before_use(origin: KeepAliveServer) -> None:
    origin.drop_after_response = True
    with _client(origin.api_url) as client:
        client.get_run("run-1")
        time.sleep(0.05)
        client.get_run("run-1")

    assert [exchange.connection for exchange in origin.exchanges] == [1, 2]


def test_submission_failure_is_not_resent(origin: KeepAliveServer) -> None:
    origin.delay_seconds = 0.5
    with _client(origin.api_url, timeout=0.1) as client, pytest.raises(AdaptOrchAPIError):
        client.submit_run({"goal": "x"}, REQUEST_ID)
    time.sleep(0.6)

    assert [exchange.method for exchange in origin.exchanges] == ["POST"]


def test_timed_out_read_on_a_reused_connection_is_not_resent(origin: KeepAliveServer) -> None:
    with _client(origin.api_url, timeout=0.2) as client:
        client.get_run("run-1")
        origin.delay_seconds = 0.5
        with pytest.raises(AdaptOrchAPIError, match="network request failed"):
            client.get_run("run-1")
    time.sleep(0.6)

    assert [exchange.method for exchange in origin.exchanges] == ["GET", "GET"]


def test_expired_idle_connection_is_not_reused(
    origin: KeepAliveServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(keepalive, "IDLE_SECONDS", 0.0)
    with _client(origin.api_url) as client:
        client.get_run("run-1")
        time.sleep(0.01)
        client.get_run("run-1")

    assert [exchange.connection for exchange in origin.exchanges] == [1, 2]


def test_rejected_body_does_not_return_its_connection(origin: KeepAliveServer) -> None:
    too_deep = b"[" * 70 + b"]" * 70
    origin.body = lambda _path: b'{"run_id":"run-1","status":"queued","x":' + too_deep + b"}"
    with _client(origin.api_url) as client:
        for _ in range(2):
            with pytest.raises(AdaptOrchAPIError):
                client.get_run("run-1")

    # A fully read but rejected body leaves the connection clean, so it is reused.
    assert [exchange.connection for exchange in origin.exchanges] == [1, 1]


def test_partially_read_body_closes_its_connection() -> None:
    origin = KeepAliveServer()
    origin.body = lambda _path: b"x" * (8 * 1024 * 1024 + 10)
    origin.start()
    try:
        with _client(origin.api_url) as client:
            for _ in range(2):
                with pytest.raises(AdaptOrchAPIError, match="size limit"):
                    client.get_run("run-1")
    finally:
        origin.close()

    assert [exchange.connection for exchange in origin.exchanges] == [1, 2]


def test_close_releases_idle_connections_and_client_stays_usable(
    origin: KeepAliveServer,
) -> None:
    client = _client(origin.api_url)
    client.get_run("run-1")
    client.close()
    client.get_run("run-1")
    client.close()

    assert [exchange.connection for exchange in origin.exchanges] == [1, 2]


def test_concurrent_reads_share_the_pool_safely(origin: KeepAliveServer) -> None:
    errors: list[BaseException] = []
    with _client(origin.api_url) as client:

        def read() -> None:
            try:
                for _ in range(10):
                    assert client.get_run("run-1").run_id == "run-1"
            except BaseException as error:  # pragma: no cover - surfaced below
                errors.append(error)

        threads = [threading.Thread(target=read) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert errors == []
    assert len(origin.exchanges) == 80
    assert origin.connections <= 8


@pytest.mark.skipif(not hasattr(socket, "TCP_QUICKACK"), reason="Linux-only TCP option")
def test_reused_reads_do_not_stall_on_a_server_that_leaves_nagle_on(
    origin: KeepAliveServer,
) -> None:
    # The fixture writes headers and body separately and never sets TCP_NODELAY. Without
    # an immediate ACK each reused read waits ~40 ms for the client's delayed ACK.
    with _client(origin.api_url) as client:
        client.get_run("run-1")
        started = time.perf_counter()
        for _ in range(20):
            client.get_run("run-1")
        elapsed = time.perf_counter() - started

    assert origin.connections == 1
    assert elapsed < 0.4, f"20 reused reads took {elapsed:.3f}s"


def test_tls_context_verifies_and_refuses_legacy_protocols() -> None:
    context = keepalive.create_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_tls_context_is_built_once_and_only_for_https(
    origin: KeepAliveServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[ssl.SSLContext] = []
    original = keepalive.create_tls_context

    def counting() -> ssl.SSLContext:
        built.append(original())
        return built[-1]

    monkeypatch.setattr(keepalive, "create_tls_context", counting)
    with _client(origin.api_url) as client:
        client.get_run("run-1")

    assert built == []


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI is unavailable")
def test_https_reuses_one_tls_session(tmp_path: Path) -> None:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    origin = KeepAliveServer()
    origin.start(
        wrap=lambda server: setattr(
            server, "socket", server_context.wrap_socket(server.socket, server_side=True)
        )
    )
    client_context = keepalive.create_tls_context()
    client_context.load_verify_locations(cert)
    transport = HTTPTransport(
        ClientConfig(api_url=f"https://localhost:{origin.port}", api_key="ado_test")
    )
    transport.close()
    handlers = keepalive.keepalive_handlers(client_context)
    transport._handlers = handlers
    transport._opener = build_opener(ProxyHandler({}), _NoRedirectHandler(), *handlers)
    try:
        for _ in range(3):
            assert transport.request(RequestSpec("GET", "/v1/runs/run-1"))["run_id"] == "run-1"
    finally:
        transport.close()
        origin.close()

    assert [exchange.connection for exchange in origin.exchanges] == [1, 1, 1]
