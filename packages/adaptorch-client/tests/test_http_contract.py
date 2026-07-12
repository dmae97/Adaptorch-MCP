from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from client_test_support import JSONMapping, LocalAPIServer, make_run_payload

from adaptorch_client import AdaptOrchClient, ClientConfig, PayloadResult


def _client(local_api: LocalAPIServer, *, api_key: str = "test-api-key") -> AdaptOrchClient:
    return AdaptOrchClient(
        ClientConfig(api_url=local_api.api_url, api_key=api_key, timeout_seconds=1.0)
    )


def test_capabilities_uses_service_bearer_auth_and_returns_typed_result(
    local_api: LocalAPIServer,
) -> None:
    expected: JSONMapping = {
        "api_version": "v1",
        "run_types": ["orchestration", "patch_verification"],
        "features": ["runs", "evidence", "artifacts"],
    }
    local_api.enqueue_json(expected)

    result = _client(local_api).capabilities()

    request = local_api.requests[0]
    assert request.method == "GET"
    assert request.path == "/v1/capabilities"
    assert request.headers["Authorization"] == "Bearer test-api-key"
    assert "X-API-Key" not in request.headers
    assert isinstance(result, PayloadResult)
    assert result.api_version == "v1"
    assert result.run_types == ("orchestration", "patch_verification")
    assert result.features == ("runs", "evidence", "artifacts")
    assert result.to_payload() == expected
    json.dumps(result.to_payload())


def test_tenant_dashboard_key_uses_only_x_api_key(local_api: LocalAPIServer) -> None:
    local_api.enqueue_json(
        {
            "api_version": "v1",
            "run_types": ["orchestration"],
            "features": ["runs"],
        }
    )

    _client(local_api, api_key="ado_tenant-dashboard-key").capabilities()

    headers = {name.lower(): value for name, value in local_api.requests[0].headers.items()}
    assert headers["x-api-key"] == "ado_tenant-dashboard-key"
    assert "authorization" not in headers


def test_whoami_returns_typed_principal(local_api: LocalAPIServer) -> None:
    expected: JSONMapping = {"subject_id": "user-1", "project_id": "project-1"}
    local_api.enqueue_json(expected)

    result = _client(local_api).whoami()

    request = local_api.requests[0]
    assert request.method == "GET"
    assert request.path == "/v1/whoami"
    assert result.subject_id == "user-1"
    assert result.project_id == "project-1"
    assert result.to_payload() == expected


def test_submit_run_sends_gateway_contract_and_uuid_idempotency_header(
    local_api: LocalAPIServer,
) -> None:
    payload: JSONMapping = {"ok": True, "run_id": "run-1", "status": "QUEUED"}
    spec: JSONMapping = {"subtasks": [{"id": "check"}], "dependencies": []}
    idempotency_key = "11111111-1111-4111-8111-111111111111"
    local_api.enqueue_json(payload, status=201)

    result = _client(local_api).submit_run(spec, idempotency_key)

    request = local_api.requests[0]
    assert request.method == "POST"
    assert request.path == "/v1/runs"
    assert request.headers["Authorization"] == "Bearer test-api-key"
    assert request.headers["Idempotency-Key"] == idempotency_key
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.body) == spec
    assert result.run_id == "run-1"
    assert result.status == "QUEUED"
    assert result.to_payload() == payload


def test_list_runs_omits_optional_filters_and_returns_typed_page(
    local_api: LocalAPIServer,
) -> None:
    expected: JSONMapping = {"items": [], "next_cursor": None}
    local_api.enqueue_json(expected)

    result = _client(local_api).list_runs()

    request = local_api.requests[0]
    assert request.method == "GET"
    assert request.path == "/v1/runs"
    assert result.items == ()
    assert result.next_cursor is None
    assert result.to_payload() == expected


def test_list_runs_encodes_filters_and_parses_page(local_api: LocalAPIServer) -> None:
    expected: JSONMapping = {
        "items": [make_run_payload(status="succeeded")],
        "next_cursor": "cursor-2",
    }
    local_api.enqueue_json(expected)

    result = _client(local_api).list_runs(status="succeeded", project_id="project 1")

    parsed = urlsplit(local_api.requests[0].path)
    assert local_api.requests[0].method == "GET"
    assert parsed.path == "/v1/runs"
    assert parse_qs(parsed.query) == {
        "status": ["succeeded"],
        "project_id": ["project 1"],
    }
    assert len(result.items) == 1
    assert result.items[0].run_id == "run-1"
    assert result.items[0].status == "succeeded"
    assert result.next_cursor == "cursor-2"
    assert result.to_payload() == expected


def test_get_run_uses_run_resource_path(local_api: LocalAPIServer) -> None:
    payload = make_run_payload(status="running")
    local_api.enqueue_json(payload)

    result = _client(local_api).get_run("run-1")

    request = local_api.requests[0]
    assert request.method == "GET"
    assert request.path == "/v1/runs/run-1"
    assert result.status == "running"
    assert result.kind == "orchestration"
    assert result.phase == "accepted"
    assert result.created_at == "2026-07-01T12:00:00Z"
    assert result.policy_version == "2026-07-01"
    assert result.links == {"self": "/v1/runs/run-1"}
    assert result.to_payload() == payload


def test_cancel_run_uses_gateway_put_contract(local_api: LocalAPIServer) -> None:
    local_api.enqueue_json(
        {"ok": True, "run_id": "run-1", "status": "CANCELLING"}, status=202
    )

    result = _client(local_api).cancel_run("run-1", reason="stale request")

    request = local_api.requests[0]
    assert request.method == "PUT"
    assert request.path == "/v1/runs/run-1/cancel"
    assert json.loads(request.body) == {"reason": "stale request"}
    assert result.status == "CANCELLING"


def test_cancel_run_omits_reason_when_absent(local_api: LocalAPIServer) -> None:
    local_api.enqueue_json(make_run_payload(status="cancelled"), status=202)

    _client(local_api).cancel_run("run-1")

    assert json.loads(local_api.requests[0].body) == {}


def test_get_evidence_returns_typed_report(local_api: LocalAPIServer) -> None:
    expected: JSONMapping = {
        "run_id": "run-1",
        "checks": [{"name": "tests", "status": "PASSED"}],
    }
    local_api.enqueue_json(expected)

    result = _client(local_api).get_evidence("run-1")

    request = local_api.requests[0]
    assert request.method == "GET"
    assert request.path == "/v1/runs/run-1/evidence"
    assert result.run_id == "run-1"
    assert len(result.checks) == 1
    assert (result.checks[0].name, result.checks[0].status) == ("tests", "PASSED")
    assert result.to_payload() == expected


def test_list_artifacts_returns_typed_items(local_api: LocalAPIServer) -> None:
    expected: JSONMapping = {
        "run_id": "run-1",
        "items": [
            {
                "artifact_id": "artifact-1",
                "name": "report.json",
                "media_type": "application/json",
                "size_bytes": 2048,
                "sha256": "0" * 64,
                "download_url": "https://downloads.example.com/artifact-1",
            }
        ],
    }
    local_api.enqueue_json(expected)

    result = _client(local_api).list_artifacts("run-1")

    request = local_api.requests[0]
    assert request.method == "GET"
    assert request.path == "/v1/runs/run-1/artifacts"
    assert result.run_id == "run-1"
    assert len(result.items) == 1
    artifact = result.items[0]
    assert artifact.artifact_id == "artifact-1"
    assert artifact.name == "report.json"
    assert artifact.media_type == "application/json"
    assert artifact.size_bytes == 2048
    assert artifact.sha256 == "0" * 64
    assert artifact.download_url == "https://downloads.example.com/artifact-1"
    assert result.to_payload() == expected
