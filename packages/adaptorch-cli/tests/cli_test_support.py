from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pytest

_FAKE_CLIENT = '''\
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def validate_api_url(api_url):
    try:
        parsed = urlsplit(api_url)
        hostname = parsed.hostname
    except ValueError:
        raise ValueError("api_url is invalid") from None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or hostname is None:
        raise ValueError("api_url must be an http(s) origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("api_url must not include credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("api_url must not include a path, query, or fragment")
    if parsed.scheme == "http" and hostname not in _LOOPBACK_HOSTS:
        raise ValueError("HTTP is allowed only for exact loopback hosts")
    return api_url.rstrip("/")


class ClientError(Exception):
    status_code = 500


class AuthenticationError(ClientError):
    status_code = 401


class NotFoundError(ClientError):
    status_code = 404


class ConflictError(ClientError):
    status_code = 409


class RateLimitError(ClientError):
    status_code = 429


class TransportError(ClientError):
    status_code = 503


ApiError = ClientError
AdaptOrchAPIError = ClientError
AuthError = AuthenticationError
QuotaError = RateLimitError


@dataclass(frozen=True, slots=True)
class ClientConfig:
    api_url: str
    api_key: str
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class ApiResult:
    payload: dict

    def to_payload(self):
        return self.payload


def _record(method, args=None, kwargs=None):
    path = Path(os.environ["FAKE_CLIENT_LOG"])
    entry = {"method": method, "args": args or [], "kwargs": kwargs or {}}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\\n")


def _fail_if_requested():
    error = os.environ.get("FAKE_CLIENT_ERROR")
    errors = {
        "auth": AuthenticationError,
        "not_found": NotFoundError,
        "conflict": ConflictError,
        "rate_limit": RateLimitError,
        "transport": TransportError,
        "api": ClientError,
    }
    if error == "interrupt":
        raise KeyboardInterrupt
    if error in errors:
        raise errors[error](error)


class AdaptOrchClient:
    def __init__(self, config):
        _record("init", [config.api_url, config.api_key])

    def whoami(self):
        _fail_if_requested()
        _record("whoami")
        return ApiResult({"email": "user@example.test", "id": "user-1"})

    def capabilities(self):
        _fail_if_requested()
        _record("capabilities")
        return ApiResult({"capabilities": ["runs", "evidence", "artifacts"]})

    def submit_run(self, payload, idempotency_key):
        _fail_if_requested()
        if not 1 <= len(idempotency_key) <= 200:
            raise ValueError("invalid idempotency key")
        _record("submit_run", [payload], {"idempotency_key": idempotency_key})
        return ApiResult({"id": "run-1", "status": "QUEUED"})

    def list_runs(self, status=None, project_id=None):
        _fail_if_requested()
        _record("list_runs", [], {"status": status, "project_id": project_id})
        return ApiResult({"runs": [{"id": "run-1", "status": "QUEUED"}]})

    def get_run(self, run_id):
        _fail_if_requested()
        _record("get_run", [run_id])
        run = {"id": run_id, "status": os.environ.get("FAKE_RUN_STATUS", "RUNNING")}
        if os.environ.get("FAKE_RUN_WRAP") == "data":
            return ApiResult({"data": run})
        return ApiResult(run)

    def cancel_run(self, run_id, reason=None):
        _fail_if_requested()
        _record("cancel_run", [run_id], {"reason": reason})
        return ApiResult({"id": run_id, "status": "CANCELLED"})

    def get_evidence(self, run_id):
        _fail_if_requested()
        _record("get_evidence", [run_id])
        return ApiResult({"evidence": [{"kind": "test", "run_id": run_id}]})

    def list_artifacts(self, run_id):
        _fail_if_requested()
        _record("list_artifacts", [run_id])
        return ApiResult({"artifacts": [{"name": "result.json", "run_id": run_id}]})
'''


@dataclass(frozen=True, slots=True)
class CliResult:
    returncode: int
    stdout: str
    stderr: str
    client_log: str


class CliRunner(Protocol):
    def __call__(self, args: list[str], input_text: str | None = None) -> CliResult: ...


@pytest.fixture
def run_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> CliRunner:
    fake_root = tmp_path / "fake"
    fake_package = fake_root / "adaptorch_client"
    fake_package.mkdir(parents=True)
    (fake_package / "__init__.py").write_text(_FAKE_CLIENT, encoding="utf-8")
    log_path = tmp_path / "client.jsonl"

    source_root = Path(__file__).parents[1] / "src"
    inherited_path = os.environ.get("PYTHONPATH")
    python_path = os.pathsep.join(
        part for part in (str(fake_root), str(source_root), inherited_path) if part
    )
    monkeypatch.setenv("PYTHONPATH", python_path)
    monkeypatch.setenv("FAKE_CLIENT_LOG", str(log_path))
    monkeypatch.setenv("ADAPTORCH_API_KEY", "env-test-key")

    def invoke(args: list[str], input_text: str | None = None) -> CliResult:
        completed = subprocess.run(
            [sys.executable, "-m", "adaptorch_cli", *args],
            check=False,
            capture_output=True,
            env=os.environ.copy(),
            input=input_text,
            text=True,
        )
        client_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        if log_path.exists():
            log_path.unlink()
        return CliResult(completed.returncode, completed.stdout, completed.stderr, client_log)

    return invoke
