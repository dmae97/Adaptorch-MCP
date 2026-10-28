from __future__ import annotations

import hashlib
import json

import pytest
from client_test_support import JSONMapping, LocalAPIServer

from adaptorch_client import AdaptOrchAPIError, AdaptOrchClient, ClientConfig, RunReport

_PDF = b"%PDF-1.7\nsynthetic report bytes\n%%EOF\n"


def _client(api: LocalAPIServer) -> AdaptOrchClient:
    return AdaptOrchClient(ClientConfig(api_url=api.api_url, api_key="test-api-key"))


def _report(run_id: str = "run-1") -> JSONMapping:
    return {
        "schema_version": "adaptorch-run-report.v1",
        "run": {"run_id": run_id, "status": "SUCCEEDED"},
        "io": {"output": {"state": "RECORDED", "value": "SYNTHETIC answer"}},
        "snapshot_sha256": "a" * 64,
    }


def _enqueue_json_report(api: LocalAPIServer, payload: JSONMapping) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    api.enqueue_raw(body, headers={"Content-Type": "application/json"})
    return body


def test_json_report_keeps_exact_bytes_and_exposes_the_saved_answer(
    local_api: LocalAPIServer,
) -> None:
    body = _enqueue_json_report(local_api, _report())

    report = _client(local_api).get_run_report("run-1")

    request = local_api.requests[0]
    assert (request.method, request.path) == ("GET", "/v1/runs/run-1/report.json")
    assert request.headers["Accept"] == "application/json"
    assert request.headers["Authorization"] == "Bearer test-api-key"
    assert isinstance(report, RunReport)
    assert (report.run_id, report.format) == ("run-1", "json")
    assert report.media_type == "application/json"
    assert report.content == body
    assert report.sha256 == hashlib.sha256(body).hexdigest()
    assert report.snapshot_sha256 == "a" * 64
    assert report.to_payload() == {
        "run_id": "run-1",
        "format": "json",
        "locale": None,
        "media_type": "application/json",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "snapshot_sha256": "a" * 64,
    }


def test_pdf_report_sends_locale_and_returns_bytes(local_api: LocalAPIServer) -> None:
    local_api.enqueue_raw(_PDF, headers={"Content-Type": "application/pdf"})

    report = _client(local_api).get_run_report("run/1", format="pdf", locale="zh-CN")

    request = local_api.requests[0]
    assert request.path == "/v1/runs/run%2F1/report.pdf?locale=zh-CN"
    assert request.headers["Accept"] == "application/pdf"
    assert report.content == _PDF
    assert (report.format, report.locale, report.snapshot_sha256) == ("pdf", "zh-CN", None)
    assert "content" not in repr(report)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"format": "html"}, "format"),
        ({"format": "pdf", "locale": "fr"}, "locale"),
        ({"format": "json", "locale": "ko"}, "locale"),
    ],
)
def test_invalid_options_are_refused_before_any_request(
    local_api: LocalAPIServer, kwargs: dict[str, str], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _client(local_api).get_run_report("run-1", **kwargs)  # type: ignore[arg-type]
    assert local_api.requests == []


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (json.dumps(_report("other-run")).encode(), "application/json"),
        (b'{"run":{"run_id":"run-1"}}', "application/json"),
        (b"[1]", "application/json"),
        (json.dumps(_report()).encode(), "text/html"),
    ],
)
def test_json_report_that_cannot_be_bound_to_the_run_is_rejected(
    local_api: LocalAPIServer, body: bytes, content_type: str
) -> None:
    local_api.enqueue_raw(body, headers={"Content-Type": content_type})
    with pytest.raises(AdaptOrchAPIError):
        _client(local_api).get_run_report("run-1")


@pytest.mark.parametrize(
    ("body", "content_type"),
    [(b"<html>login</html>", "application/pdf"), (_PDF, "application/json")],
)
def test_pdf_with_wrong_signature_or_type_is_rejected(
    local_api: LocalAPIServer, body: bytes, content_type: str
) -> None:
    local_api.enqueue_raw(body, headers={"Content-Type": content_type})
    with pytest.raises(AdaptOrchAPIError):
        _client(local_api).get_run_report("run-1", format="pdf")


@pytest.mark.parametrize("status", [404, 409, 503])
def test_server_errors_keep_their_status(local_api: LocalAPIServer, status: int) -> None:
    local_api.enqueue_json({"detail": "Run report not found"}, status=status)
    with pytest.raises(AdaptOrchAPIError) as caught:
        _client(local_api).get_run_report("run-1", format="pdf")
    assert caught.value.status_code == status


def test_oversized_report_is_rejected_from_the_declared_length(local_api: LocalAPIServer) -> None:
    local_api.enqueue_raw(
        _PDF,
        headers={"Content-Type": "application/pdf", "Content-Length": str(64 * 1024 * 1024)},
    )
    with pytest.raises(AdaptOrchAPIError, match="size"):
        _client(local_api).get_run_report("run-1", format="pdf")
