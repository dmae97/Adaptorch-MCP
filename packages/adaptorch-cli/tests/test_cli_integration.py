from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from queue import Queue
from threading import Thread

_TEST_TOKEN = "adaptorch-integration-placeholder"
_REQUEST_ID = "33333333-3333-4333-8333-333333333333"
_REQUEST_BODY = b'{"dependencies":[],"subtasks":[{"id":"verify","prompt":"verify composition"}]}'
_RESPONSE_BODY = b'{"ok":true,"run_id":"run-real","status":"QUEUED"}'
_REQUEST_INPUT = (
    '{"subtasks":[{"id":"verify","prompt":"verify composition"}],"dependencies":[]}\n'
)


@dataclass(frozen=True, slots=True)
class CapturedRequest:
    method: str
    path: str
    authorization: str
    idempotency_key: str
    body: bytes


class RunHandler(BaseHTTPRequestHandler):
    captured: Queue[CapturedRequest] = Queue()

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.captured.put(
            CapturedRequest(
                method=self.command,
                path=self.path,
                authorization=self.headers["Authorization"],
                idempotency_key=self.headers["Idempotency-Key"],
                body=body,
            )
        )
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_RESPONSE_BODY)))
        self.end_headers()
        self.wfile.write(_RESPONSE_BODY)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_run_submit_composes_cli_with_real_client_over_loopback() -> None:
    cli_source = Path(__file__).parents[1] / "src"
    client_source = Path(__file__).parents[2] / "adaptorch-client" / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(cli_source), str(client_source)))
    env["ADAPTORCH_API_KEY"] = _TEST_TOKEN
    proxy_names = (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "all_proxy",
        "https_proxy",
        "http_proxy",
    )
    for name in proxy_names:
        env.pop(name, None)

    with HTTPServer(("127.0.0.1", 0), RunHandler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "adaptorch_cli",
                    "--api-url",
                    f"http://127.0.0.1:{server.server_port}",
                    "--output",
                    "json",
                    "run",
                    "submit",
                    "--file",
                    "-",
                    "--request-id",
                    _REQUEST_ID,
                ],
                check=False,
                capture_output=True,
                env=env,
                input=_REQUEST_INPUT,
                text=True,
                timeout=10,
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)

    request = RunHandler.captured.get_nowait()
    assert request == CapturedRequest(
        method="POST",
        path="/v1/runs",
        authorization=f"Bearer {_TEST_TOKEN}",
        idempotency_key=_REQUEST_ID,
        body=_REQUEST_BODY,
    )
    assert completed.returncode == 0
    assert completed.stdout == '{"ok":true,"run_id":"run-real","status":"QUEUED"}\n'
    assert completed.stderr == ""
    assert _TEST_TOKEN not in completed.stdout
    assert _TEST_TOKEN not in completed.stderr
