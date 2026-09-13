"""Public SDK workflow over a real loopback HTTP server, with no provider execution."""

from __future__ import annotations

import json

import pytest
from client_test_support import LocalAPIServer

from adaptorch_client import (
    AdaptOrchAPIError,
    AdaptOrchClient,
    ClientConfig,
    PollPolicy,
    ProviderCredential,
)


def test_submit_once_then_poll_and_read_bound_evidence_without_leaking_byok(
    local_api: LocalAPIServer,
) -> None:
    local_api.enqueue_json(
        {
            "api_version": "v1",
            "features": ["runs", "evidence", "artifacts"],
            "server_build": "6955c1564",
            "receipt_schema_version": "verification.receipt/v2",
        }
    )
    local_api.enqueue_json(
        {
            "run_id": "r1",
            "status": "QUEUED",
            "synthesis_mode_requested": "auto",
            "synthesis_mode_used": "robust",
            "auto_synthesis_reason": "default",
        },
        status=201,
    )
    local_api.enqueue_json({"run_id": "r1", "status": "RUNNING"})
    local_api.enqueue_json(
        {
            "run_id": "r1",
            "status": "SUCCEEDED",
            "result_status": "DEGRADED",
            "synthesis_mode": "robust",
            "evaluation_status": "PENDING",
        }
    )
    local_api.enqueue_json({"run_id": "r1", "checks": [{"name": "runner", "status": "ENV_ERROR"}]})
    local_api.enqueue_json(
        {"run_id": "r1", "artifacts": {"report": "/v1/runs/r1/artifacts/report"}}
    )
    client = AdaptOrchClient(ClientConfig(local_api.api_url, "ado_synthetic", timeout_seconds=1))
    credential = ProviderCredential("provider", "model", "provider-synthetic-secret")

    capabilities = client.capabilities()
    admitted = client.submit_run(
        {"subtasks": [{"id": "t1", "description": "fixture"}], "synthesis_mode": "auto"},
        "11111111-1111-4111-8111-111111111111",
        provider_credential=credential,
    )
    observed = client.wait_for_run(
        admitted.run_id, policy=PollPolicy(interval_seconds=0, max_polls=2)
    )
    evidence = client.get_evidence(admitted.run_id)
    artifacts = client.list_artifacts(admitted.run_id)

    assert capabilities.server_build == "6955c1564"
    assert admitted.synthesis_mode_requested == "auto" and admitted.synthesis_mode_used == "robust"
    assert observed.reason.value == "terminal" and observed.polls == 2
    assert observed.run is not None and observed.run.result_status == "DEGRADED"
    assert observed.run.synthesis_mode_used is None  # GET did not report admission metadata.
    assert evidence.checks[0].status == "ENV_ERROR"
    assert artifacts.artifact_urls == {"report": "/v1/runs/r1/artifacts/report"}
    assert [request.method for request in local_api.requests] == [
        "GET",
        "POST",
        "GET",
        "GET",
        "GET",
        "GET",
    ]
    for request in local_api.requests:
        headers = {key.lower(): value for key, value in request.headers.items()}
        if request.method == "POST":
            assert headers["x-provider"] == "provider"
            assert headers["x-provider-model"] == "model"
            assert headers["x-provider-key"] == credential.api_key
            assert json.loads(request.body)["synthesis_mode"] == "auto"
            assert credential.api_key not in request.body.decode()
        else:
            assert not any(key.startswith("x-provider") for key in headers)


def test_failed_submission_is_one_request_with_both_credentials_redacted(
    local_api: LocalAPIServer,
) -> None:
    credential = ProviderCredential("provider", "model", "provider-test-secret")
    local_api.enqueue_json(
        {
            "error": {
                "code": "UNAVAILABLE",
                "message": "ado_test provider-test-secret",
            }
        },
        status=503,
    )
    client = AdaptOrchClient(ClientConfig(local_api.api_url, "ado_test"))
    with pytest.raises(AdaptOrchAPIError) as error:
        client.submit_run(
            {}, "11111111-1111-4111-8111-111111111111", provider_credential=credential
        )
    assert len(local_api.requests) == 1
    assert "ado_test" not in str(error.value) and credential.api_key not in str(error.value)


def test_polling_foreign_subject_stops_after_one_read(local_api: LocalAPIServer) -> None:
    local_api.enqueue_json({"run_id": "foreign", "status": "SUCCEEDED"})
    client = AdaptOrchClient(ClientConfig(local_api.api_url, "ado_test"))
    with pytest.raises(AdaptOrchAPIError):
        client.wait_for_run("expected", policy=PollPolicy(interval_seconds=0))
    assert len(local_api.requests) == 1 and local_api.requests[0].method == "GET"
