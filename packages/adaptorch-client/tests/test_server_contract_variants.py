"""Public v1 structured records and current control-plane reference maps stay distinct."""

from __future__ import annotations

import pytest

from adaptorch_client import AdaptOrchAPIError, ArtifactListResponse, CapabilitySet, JSONMapping


def test_capabilities_preserve_reported_contract_and_build_versions() -> None:
    # Given server-reported version metadata, not a locally invented engine version.
    payload: JSONMapping = {
        "api_version": "v1",
        "features": ["runs", "evidence", "artifacts"],
        "server_build": "6955c1564",
        "receipt_schema_version": "verification.receipt/v2",
        "evidence_schema_version": "verification.evidence/v2",
        "mcp_toolset_version": "2026-09-04",
        "supported_mcp_protocols": ["2024-11-05"],
    }
    result = CapabilitySet.from_payload(payload)
    assert result.server_build == "6955c1564"
    assert result.receipt_schema_version == "verification.receipt/v2"
    assert result.evidence_schema_version == "verification.evidence/v2"
    assert result.mcp_toolset_version == "2026-09-04"
    assert result.supported_mcp_protocols == ("2024-11-05",)
    assert result.to_payload() == payload


def test_absent_capability_versions_remain_unmeasured() -> None:
    result = CapabilitySet.from_payload({"api_version": "v1", "features": []})
    assert result.server_build is None and result.receipt_schema_version is None
    assert result.supported_mcp_protocols == ()


def test_reference_map_does_not_invent_artifact_ids_or_integrity_hashes() -> None:
    payload: JSONMapping = {
        "run_id": "r1",
        "artifacts": {"report.json": "/v1/runs/r1/artifacts/report.json"},
    }
    result = ArtifactListResponse.from_payload(payload)
    assert result.items[0].artifact_id == "report.json"
    assert result.items[0].name == "report.json"
    assert result.items[0].sha256 is None
    assert result.items[0].download_url is None
    assert result.artifact_urls == payload["artifacts"]
    assert result.to_payload() == payload


def test_structured_artifacts_keep_their_original_representation() -> None:
    payload: JSONMapping = {"run_id": "r1", "items": [{"artifact_id": "a1", "name": "report.json"}]}
    result = ArtifactListResponse.from_payload(payload)
    assert result.items[0].artifact_id == "a1" and result.artifact_urls is None


@pytest.mark.parametrize(
    "payload",
    [
        {"run_id": "r1", "artifacts": {"report": 1}},
        {"run_id": "r1", "items": [], "artifacts": {}},
        {"run_id": "r1", "artifacts": []},
    ],
)
def test_ambiguous_or_malformed_artifact_containers_are_rejected(payload: JSONMapping) -> None:
    with pytest.raises(AdaptOrchAPIError):
        ArtifactListResponse.from_payload(payload)
