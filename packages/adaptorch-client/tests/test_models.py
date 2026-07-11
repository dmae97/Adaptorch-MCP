from __future__ import annotations

import pytest
from client_test_support import make_run_payload

from adaptorch_client import (
    AdaptOrchAPIError,
    ArtifactListResponse,
    CapabilitySet,
    EvidenceReport,
    JSONMapping,
    JSONValue,
    Principal,
    Run,
    RunListResponse,
)


def _artifact_listing(size_bytes: JSONValue) -> JSONMapping:
    return {
        "run_id": "run-1",
        "items": [
            {
                "artifact_id": "artifact-1",
                "name": "report.json",
                "size_bytes": size_bytes,
            }
        ],
    }


def test_run_preserves_unknown_status_enum_and_payload() -> None:
    payload = make_run_payload(status="paused_for_review")

    result = Run.from_payload(payload)

    assert result.status == "paused_for_review"
    assert result.to_payload() == payload


def test_run_parses_canonical_fields() -> None:
    result = Run.from_payload(make_run_payload(status="succeeded"))

    assert result.run_id == "run-1"
    assert result.kind == "orchestration"
    assert result.status == "succeeded"
    assert result.phase == "accepted"
    assert result.created_at == "2026-07-01T12:00:00Z"
    assert result.policy_version == "2026-07-01"
    assert result.links == {"self": "/v1/runs/run-1"}


def test_run_defaults_optional_fields_to_none() -> None:
    result = Run.from_payload({"run_id": "run-1", "status": "queued"})

    assert result.kind is None
    assert result.phase is None
    assert result.created_at is None
    assert result.policy_version is None
    assert result.links is None


def test_run_tolerates_and_preserves_unknown_additive_fields() -> None:
    payload = make_run_payload()
    payload["queue_position"] = 3
    payload["server_hint"] = {"future": True}

    result = Run.from_payload(payload)

    assert result.to_payload() == payload


@pytest.mark.parametrize("missing", ["run_id", "status"])
def test_run_rejects_missing_required_field(missing: str) -> None:
    payload = make_run_payload()
    del payload[missing]

    with pytest.raises(AdaptOrchAPIError):
        Run.from_payload(payload)


def test_run_rejects_non_string_link_target() -> None:
    payload = make_run_payload()
    payload["links"] = {"self": 7}

    with pytest.raises(AdaptOrchAPIError):
        Run.from_payload(payload)


def test_run_rejects_non_object_links() -> None:
    payload = make_run_payload()
    payload["links"] = ["not-an-object"]

    with pytest.raises(AdaptOrchAPIError):
        Run.from_payload(payload)


def test_run_list_parses_items_and_next_cursor() -> None:
    payload: JSONMapping = {
        "items": [make_run_payload(status="succeeded")],
        "next_cursor": "cursor-2",
    }

    result = RunListResponse.from_payload(payload)

    assert len(result.items) == 1
    assert result.items[0].run_id == "run-1"
    assert result.items[0].status == "succeeded"
    assert result.next_cursor == "cursor-2"
    assert result.to_payload() == payload


def test_run_list_defaults_null_or_absent_next_cursor_to_none() -> None:
    assert RunListResponse.from_payload({"items": []}).next_cursor is None
    assert RunListResponse.from_payload({"items": [], "next_cursor": None}).next_cursor is None


def test_run_list_rejects_non_array_items() -> None:
    with pytest.raises(AdaptOrchAPIError):
        RunListResponse.from_payload({"items": {}})


def test_run_list_rejects_missing_items() -> None:
    with pytest.raises(AdaptOrchAPIError):
        RunListResponse.from_payload({})


def test_run_list_rejects_non_object_item() -> None:
    with pytest.raises(AdaptOrchAPIError):
        RunListResponse.from_payload({"items": ["not-a-run"]})


def test_capabilities_parses_direct_record() -> None:
    payload: JSONMapping = {
        "api_version": "v1",
        "run_types": ["orchestration", "patch_verification"],
        "features": ["runs", "evidence", "artifacts"],
    }

    result = CapabilitySet.from_payload(payload)

    assert result.api_version == "v1"
    assert result.run_types == ("orchestration", "patch_verification")
    assert result.features == ("runs", "evidence", "artifacts")
    assert result.to_payload() == payload


def test_capabilities_defaults_absent_run_types_to_empty() -> None:
    result = CapabilitySet.from_payload({"api_version": "v1", "features": []})

    assert result.run_types == ()


def test_capabilities_rejects_non_string_run_type() -> None:
    payload: JSONMapping = {
        "api_version": "v1",
        "run_types": ["orchestration", 7],
        "features": [],
    }

    with pytest.raises(AdaptOrchAPIError):
        CapabilitySet.from_payload(payload)


def test_capabilities_rejects_missing_features() -> None:
    with pytest.raises(AdaptOrchAPIError):
        CapabilitySet.from_payload({"api_version": "v1"})


def test_principal_defaults_optional_project_to_none() -> None:
    result = Principal.from_payload({"subject_id": "user-1"})

    assert result.subject_id == "user-1"
    assert result.project_id is None


def test_principal_rejects_missing_subject_id() -> None:
    with pytest.raises(AdaptOrchAPIError):
        Principal.from_payload({"project_id": "project-1"})


def test_evidence_report_preserves_unknown_check_status() -> None:
    payload: JSONMapping = {
        "run_id": "run-1",
        "checks": [{"name": "policy", "status": "SKIPPED_BY_POLICY"}],
    }

    result = EvidenceReport.from_payload(payload)

    assert result.run_id == "run-1"
    assert result.checks[0].name == "policy"
    assert result.checks[0].status == "SKIPPED_BY_POLICY"
    assert result.to_payload() == payload


@pytest.mark.parametrize("missing", ["name", "status"])
def test_evidence_report_rejects_incomplete_check(missing: str) -> None:
    check: JSONMapping = {"name": "tests", "status": "PASSED"}
    del check[missing]

    with pytest.raises(AdaptOrchAPIError):
        EvidenceReport.from_payload({"run_id": "run-1", "checks": [check]})


def test_evidence_report_rejects_missing_run_id() -> None:
    with pytest.raises(AdaptOrchAPIError):
        EvidenceReport.from_payload({"checks": []})


@pytest.mark.parametrize("size_bytes", [True, -1, "2048", 20.48])
def test_artifact_listing_rejects_invalid_size_bytes(size_bytes: JSONValue) -> None:
    with pytest.raises(AdaptOrchAPIError):
        ArtifactListResponse.from_payload(_artifact_listing(size_bytes))


def test_artifact_listing_accepts_zero_size_and_absent_metadata() -> None:
    result = ArtifactListResponse.from_payload(_artifact_listing(0))

    artifact = result.items[0]
    assert result.run_id == "run-1"
    assert artifact.artifact_id == "artifact-1"
    assert artifact.name == "report.json"
    assert artifact.size_bytes == 0
    assert artifact.media_type is None
    assert artifact.sha256 is None
    assert artifact.download_url is None


@pytest.mark.parametrize("missing", ["artifact_id", "name"])
def test_artifact_listing_rejects_missing_required_field(missing: str) -> None:
    payload = _artifact_listing(0)
    items = payload["items"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    del item[missing]

    with pytest.raises(AdaptOrchAPIError):
        ArtifactListResponse.from_payload(payload)


def test_contract_error_names_field_without_leaking_values() -> None:
    payload = make_run_payload()
    payload["status"] = {"secret_marker": "do-not-leak"}

    with pytest.raises(AdaptOrchAPIError) as raised:
        Run.from_payload(payload)

    message = str(raised.value)
    assert "status" in message
    assert "do-not-leak" not in message


def test_nested_contract_error_names_item_field_path() -> None:
    run = make_run_payload()
    del run["status"]

    with pytest.raises(AdaptOrchAPIError) as raised:
        RunListResponse.from_payload({"items": [run]})

    assert "items[0].status" in str(raised.value)


def test_from_payload_is_isolated_from_later_caller_mutation() -> None:
    payload = make_run_payload()
    result = Run.from_payload(payload)

    payload["status"] = "mutated"

    assert result.status == "queued"
    assert result.to_payload() != payload


def test_run_links_mutation_does_not_corrupt_to_payload() -> None:
    result = Run.from_payload(make_run_payload())

    links = result.links
    assert links is not None
    links["self"] = "mutated"

    payload = result.to_payload()
    links_payload = payload["links"]
    assert isinstance(links_payload, dict)
    assert links_payload["self"] == "/v1/runs/run-1"
