"""Server-reported algorithm observations are separate from run liveness."""

from __future__ import annotations

import pytest
from client_test_support import JSONMapping, LocalAPIServer

from adaptorch_client import AdaptOrchAPIError, AdaptOrchClient, ClientConfig, JSONValue, Run


def test_run_keeps_requested_used_and_stored_modes_separate() -> None:
    # Given the serving layer resolved auto, while the stored configuration differs.
    payload: JSONMapping = {
        "run_id": "r1",
        "status": "SUCCEEDED",
        "result_status": "DEGRADED",
        "model": "provider:model",
        "synthesis_mode": "fourier_aggressive",
        "synthesis_mode_requested": "auto",
        "synthesis_mode_used": "stable_hybrid",
        "auto_synthesis_reason": "ensemble",
        "evaluation_status": "PENDING",
        "score_validity_status": "UNSCORED",
        "consistency": 0.75,
        "duration_ms": 120,
    }
    # When parsing observations, then no value is inferred from liveness or config.
    run = Run.from_payload(payload)
    assert run.synthesis_mode_requested == "auto"
    assert run.synthesis_mode_used == "stable_hybrid"
    assert run.synthesis_mode == "fourier_aggressive"
    assert run.model == "provider:model"
    assert run.result_status == "DEGRADED"
    assert run.evaluation_status == "PENDING" and run.score_validity_status == "UNSCORED"
    assert run.consistency == 0.75 and run.duration_ms == 120
    assert run.to_payload() == payload


def test_legacy_run_does_not_invent_effective_mode_or_evaluation() -> None:
    # Given an old response without algorithm observations.
    run = Run.from_payload({"run_id": "r1", "status": "SUCCEEDED"})
    # Then completion is not an inferred mode or correctness result.
    assert run.synthesis_mode_used is None
    assert run.result_status is None and run.evaluation_status is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", 1),
        ("synthesis_mode_used", False),
        ("evaluation_status", []),
        ("consistency", True),
        ("consistency", float("nan")),
        ("consistency", 1.1),
        ("duration_ms", -1),
        ("duration_ms", True),
        ("duration_ms", "1"),
    ],
)
def test_malformed_observations_do_not_become_scalar_success(field: str, value: JSONValue) -> None:
    # Given wrong types or unmeasured numeric substitutes, when parsed, then fail closed.
    with pytest.raises(AdaptOrchAPIError):
        Run.from_payload({"run_id": "r1", "status": "SUCCEEDED", field: value})


@pytest.mark.parametrize("operation", ["run", "evidence", "artifacts", "cancel"])
def test_resource_response_cannot_describe_another_run(
    operation: str,
    local_api: LocalAPIServer,
) -> None:
    # Given a well-formed response bound to a different subject.
    local_api.enqueue_json({"run_id": "foreign", "status": "SUCCEEDED", "checks": [], "items": []})
    client = AdaptOrchClient(ClientConfig(local_api.api_url, "ado_test", timeout_seconds=1))
    # When reading or cancelling an explicitly named run, then the subject must match.
    with pytest.raises(AdaptOrchAPIError):
        match operation:
            case "run":
                client.get_run("expected")
            case "evidence":
                client.get_evidence("expected")
            case "artifacts":
                client.list_artifacts("expected")
            case "cancel":
                client.cancel_run("expected")
            case _:
                raise AssertionError(operation)
    assert len(local_api.requests) == 1
