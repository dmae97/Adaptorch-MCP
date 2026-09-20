"""Synthetic HTTP wire tests: real urllib dispatch, no sockets or providers."""

from __future__ import annotations

import inspect
import json
import traceback
from email.message import Message
from http.client import IncompleteRead
from io import BytesIO
from urllib import request
from urllib.error import URLError
from urllib.response import addinfourl
from uuid import UUID

import pytest
from adaptorch.mcp_server import AdaptOrchMCPServer
from adaptorch.n8n_connector import (
    ControlPlaneProviderCredential,
    N8nConnectorConfig,
    N8nConnectorError,
    N8nControlPlaneConnector,
    N8nHttpError,
    N8nQuotaExceededError,
)

from adaptorch_mcp.control_plane_backend import SafeControlPlaneConnector

LIMIT = 8 * 1024 * 1024
TENANT_KEY = "ado_synthetic-tenant-canary"
PROVIDER_KEY = "synthetic-provider-canary"
PAYLOAD = {"subtasks": [{"id": "task", "description": "fixture only"}]}


class WireResponse(addinfourl):
    msg = "synthetic reason " + PROVIDER_KEY


class Wire:
    def __init__(self) -> None:
        self.replies: list[tuple[int, bytes]] = [(200, b"{}")]
        self.headers: dict[str, str] = {}
        self.calls: list[request.Request] = []
        self.streams: list[BytesIO] = []
        self.read_sizes: list[int | None] = []
        self.sleeps: list[float] = []
        self.failure: OSError | IncompleteRead | None = None

    def open(self, req: request.Request) -> addinfourl:
        self.calls.append(req)
        if self.failure is not None:
            raise self.failure
        status, raw = self.replies[0]
        if len(self.replies) > 1:
            self.replies.pop(0)
        sizes = self.read_sizes

        class Stream(BytesIO):
            def read(self, size: int | None = -1) -> bytes:
                sizes.append(size)
                return super().read(size)

        stream = Stream(raw)
        self.streams.append(stream)
        headers = Message()
        for key, value in self.headers.items():
            headers[key] = value
        return WireResponse(stream, headers, req.full_url, status)


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    result = Wire()
    monkeypatch.setattr(request.HTTPHandler, "http_open", lambda _, req: result.open(req))
    monkeypatch.setattr(request.HTTPSHandler, "https_open", lambda _, req: result.open(req))
    return result


@pytest.fixture
def backend(wire: Wire) -> SafeControlPlaneConnector:
    return SafeControlPlaneConnector(
        N8nConnectorConfig(
            base_url="http://control.invalid/prefix",
            api_token=TENANT_KEY,
            connector_source="mcp",
            provider_credential=ControlPlaneProviderCredential("openai", "fixture", PROVIDER_KEY),
        ),
        sleep_fn=wire.sleeps.append,
    )


def test_constructor_task_poll_collect_and_request_signature_are_parent_owned() -> None:
    assert issubclass(SafeControlPlaneConnector, N8nControlPlaneConnector)
    for name in ("__init__", "run_task", "wait_for_run_terminal", "run_task_and_collect"):
        assert getattr(SafeControlPlaneConnector, name) is getattr(N8nControlPlaneConnector, name)
    assert inspect.signature(SafeControlPlaneConnector._request_json) == inspect.signature(
        N8nControlPlaneConnector._request_json
    )


@pytest.mark.parametrize("failure", [503, 429, "transport", "truncated"])
def test_post_transient_failure_has_one_attempt_and_sanitized_error(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    failure: int | str,
) -> None:
    if isinstance(failure, int):
        wire.replies = [(failure, json.dumps({"detail": TENANT_KEY + PROVIDER_KEY}).encode())]
    else:
        wire.failure = URLError(PROVIDER_KEY) if failure == "transport" else IncompleteRead(b"x")
    with pytest.raises(N8nConnectorError) as caught:
        backend.run_task(payload=PAYLOAD)
    assert len(wire.calls) == 1
    assert wire.sleeps == []
    assert UUID(wire.calls[0].get_header("Idempotency-key")).version == 4
    text = repr(caught.value) + "".join(traceback.format_exception(caught.value))
    assert TENANT_KEY not in text and PROVIDER_KEY not in text
    assert TENANT_KEY not in repr(backend) and PROVIDER_KEY not in repr(backend)
    if isinstance(failure, int):
        assert isinstance(caught.value, N8nHttpError)
        assert caught.value.status_code == failure


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("location", ["/other", "https://other.invalid/target"])
def test_all_methods_refuse_redirects(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    method: str,
    status: int,
    location: str,
) -> None:
    wire.replies = [(status, b"{}")]
    wire.headers["Location"] = location
    with pytest.raises(N8nHttpError) as caught:
        backend._request_json(method, "/v1/runs", include_provider_credential=True)
    assert caught.value.status_code == status
    assert len(wire.calls) == 1 and all(stream.closed for stream in wire.streams)


@pytest.mark.parametrize(
    "method,path,include",
    [
        ("POST", "/v1/runs", True),
        ("POST", "/v1/runs", False),
        ("GET", "/v1/runs", True),
        ("PUT", "/v1/runs/r/cancel", True),
        ("POST", "/v1/benchmark-runs", True),
        ("POST", "/v1/runs/", True),
        ("POST", "/v1/runs?x=1", True),
    ],
)
def test_provider_headers_only_on_explicit_run_post(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    method: str,
    path: str,
    include: bool,
) -> None:
    # Successful run POSTs now carry a real admission subject, even in header-only fixtures.
    wire.replies = [(200, b'{"run_id":"r1","status":"QUEUED"}')]
    backend._request_json(method, path, include_provider_credential=include)
    headers = dict(wire.calls[0].header_items())
    provider = {key: value for key, value in headers.items() if key.startswith("X-provider")}
    expected = {
        "X-provider": "openai",
        "X-provider-model": "fixture",
        "X-provider-key": PROVIDER_KEY,
    }
    assert provider == (expected if (method, path, include) == ("POST", "/v1/runs", True) else {})
    assert headers["X-api-key"] == TENANT_KEY
    assert headers["X-adaptorch-connector-source"] == "mcp"


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.invalid/v1/runs",
        "//evil.invalid/v1/runs",
        "///evil.invalid/runs",
        "\n/v1/runs",
        "/v1/ru\x00ns",
        "/v1/runs\r\nx: y",
        "/v1/runs#fragment",
        "/v1/../runs",
        "/v1/%2e%2e/runs",
        "/\\evil.invalid/runs",
        "/v1/%0aruns",
        "/v1/a%3F/../../runs",
        "/v1/\x85runs",
    ],
)
def test_unsafe_paths_are_rejected_before_forwarding_credentials(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    path: str,
) -> None:
    with pytest.raises(N8nConnectorError):
        backend._request_json("POST", path, include_provider_credential=True)
    assert wire.calls == []


def test_ambient_proxy_is_ignored_and_base_path_preserved(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://ambient.invalid:9999")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setattr(request, "_opener", None)
    backend.get_usage()
    assert wire.calls[0].host == "control.invalid"
    assert wire.calls[0].selector == "/prefix/v1/usage"
    assert not wire.calls[0].has_proxy()


@pytest.mark.parametrize("endpoint", ["summary", "artifacts"])
@pytest.mark.parametrize("subject", ["wrong-subject", None, 7])
def test_wrong_subject_is_rejected_before_inherited_collection(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    endpoint: str,
    subject: str | int | None,
) -> None:
    summary = {"run_id": subject if endpoint == "summary" else "r", "status": "SUCCEEDED"}
    artifact = {"run_id": subject, "artifacts": {"report": "private-sibling"}}
    records = ({"run_id": "r"}, summary, artifact)
    wire.replies = [(200, json.dumps(item).encode()) for item in records]

    result = backend.run_task_and_collect(payload=PAYLOAD)

    # The subject guard still refuses the foreign record. Since the stability
    # bundle, a collection failure no longer discards the admitted run: the
    # read is marked blocked and the caller keeps the run_id to resume with,
    # instead of losing it to an exception and resubmitting the work.
    assert "private-sibling" not in json.dumps(result)
    assert result["run_id"] == "r"
    if endpoint == "summary":
        assert result["collection_status"] == "blocked"
    else:
        assert result["collection_status"] == "complete"
        assert result["artifact_status"] == "blocked"
        assert not result.get("artifact_urls")
    guaranteed = result["consumer_receipt"]["correctness_guaranteed"]
    assert isinstance(guaranteed, bool) and not guaranteed
    assert len(wire.calls) == (2 if endpoint == "summary" else 3)


def test_subject_guard_still_raises_on_a_direct_read(
    backend: SafeControlPlaneConnector,
    wire: Wire,
) -> None:
    """Collection degrades to `blocked`; a direct read must still fail loudly.

    Only the collection helper is allowed to convert a refusal into status.
    ``get_run`` has no run to preserve, so a foreign subject stays an error.
    """
    wire.replies = [(200, json.dumps({"run_id": "other", "status": "SUCCEEDED"}).encode())]

    with pytest.raises(N8nConnectorError, match="subject"):
        backend.get_run("r")


def test_parent_collection_keeps_polling_idempotency_and_creation_receipt(
    backend: SafeControlPlaneConnector,
    wire: Wire,
) -> None:
    wire.replies = [
        (200, json.dumps(item).encode())
        for item in (
            {"run_id": "r", "synthesis_mode_requested": "robust", "synthesis_mode_used": "paper"},
            {"run_id": "r", "status": "RUNNING"},
            {"run_id": "r", "status": "SUCCEEDED"},
            {"run_id": "r", "artifacts": {"report": "local-result"}},
        )
    ]
    result = backend.run_task_and_collect(payload=PAYLOAD, poll_interval_seconds=0.1)
    assert result["run_id"] == "r" and result["artifact_urls"] == {"report": "local-result"}
    assert result["synthesis_mode_requested"] == "robust"
    assert result["synthesis_mode_used"] == "paper"
    assert [call.get_method() for call in wire.calls] == ["POST", "GET", "GET", "GET"]
    assert wire.sleeps == [0.1]
    assert all(call.get_header("X-provider-key") is None for call in wire.calls[1:])


@pytest.mark.parametrize("status", [200, 400, 429, 503])
@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"{",
        b"\xff",
        b'{"x":1,"x":2}',
        b'{"x":{"a":1,"\\u0061":2}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e400}',
        b'{"x":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"}",
    ],
    ids=[
        "empty",
        "array",
        "broken",
        "utf8",
        "duplicate",
        "nested-duplicate",
        "nan",
        "inf",
        "negative-inf",
        "overflow",
        "deep",
    ],
)
def test_malformed_duplicate_and_nonfinite_responses_fail_closed(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    status: int,
    raw: bytes,
) -> None:
    wire.replies = [(status, raw)]
    with pytest.raises(N8nConnectorError):
        backend.get_usage()
    assert len(wire.calls) == 1 and all(stream.closed for stream in wire.streams)


@pytest.mark.parametrize("status", [200, 429, 503])
@pytest.mark.parametrize("extra", [0, 1])
def test_response_size_is_bounded_even_on_errors(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    status: int,
    extra: int,
) -> None:
    wire.replies = [(status, b'{"x":"' + b"a" * (LIMIT - 8 + extra) + b'"}')]
    if extra or status != 200:
        with pytest.raises(N8nConnectorError):
            backend.get_usage()
    else:
        assert len(backend.get_usage()["x"]) == LIMIT - 8
    assert wire.read_sizes
    assert all(size is not None and 0 <= size <= LIMIT + 1 for size in wire.read_sizes)
    assert len(wire.calls) == 1 and all(stream.closed for stream in wire.streams)


@pytest.mark.parametrize("length", [str(LIMIT + 1), "-1", "invalid", "3"])
def test_invalid_declared_length_fails_closed(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    length: str,
) -> None:
    wire.headers["Content-Length"] = length
    with pytest.raises(N8nConnectorError):
        backend.get_usage()
    assert len(wire.calls) == 1 and all(stream.closed for stream in wire.streams)


@pytest.mark.parametrize(
    "value", ["a" * LIMIT, float("nan"), float("inf")], ids=["oversize", "nan", "infinity"]
)
def test_invalid_or_oversize_requests_never_reach_wire(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    value: str | float,
) -> None:
    with pytest.raises(N8nConnectorError):
        backend._request_json("POST", "/v1/runs", body={"x": value})
    assert wire.calls == []


def test_quota_refusal_keeps_engine_usage_projection_without_private_error_text(
    backend: SafeControlPlaneConnector,
    wire: Wire,
) -> None:
    wire.replies = [
        (
            429,
            json.dumps(
                {
                    "error": "QUOTA_EXCEEDED",
                    "quota_limit": 10,
                    "quota_used": 11,
                    "quota_remaining": 0,
                    "grace_exhausted": True,
                    "plan_level": PROVIDER_KEY,
                    "detail": TENANT_KEY,
                    "private": "drop-me",
                }
            ).encode(),
        )
    ]
    with pytest.raises(N8nQuotaExceededError) as caught:
        backend.run_task(payload=PAYLOAD)
    assert caught.value.usage == {
        "error": "QUOTA_EXCEEDED",
        "limit": 10,
        "used": 11,
        "remaining": 0,
        "grace_exhausted": True,
        "plan_level": "[redacted]",
    }
    assert TENANT_KEY not in str(caught.value) and PROVIDER_KEY not in repr(caught.value)
    assert len(wire.calls) == 1 and wire.sleeps == []


def test_engine_mcp_recognizes_quota_without_turning_it_into_internal_error(
    backend: SafeControlPlaneConnector,
    wire: Wire,
) -> None:
    wire.replies = [(429, b'{"error":"QUOTA_EXCEEDED","quota_limit":10,"quota_used":11}')]
    response = AdaptOrchMCPServer(backend=backend).handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "adaptorch_usage", "arguments": {}},
        }
    )
    assert response is not None and "error" not in response
    result = response["result"]
    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"])["usage"]["used"] == 11
