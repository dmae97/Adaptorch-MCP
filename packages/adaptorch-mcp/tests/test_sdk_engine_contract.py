"""Live installed-engine projections cross both client boundaries without algorithm copies."""

from __future__ import annotations

from adaptorch.n8n_connector import build_n8n_node_output
from adaptorch.release_manifest import capabilities_payload

from adaptorch_client import CapabilitySet, Run
from adaptorch_mcp.output_schema import project_tool_output


def test_sdk_parses_the_installed_engines_real_version_handshake() -> None:
    # Given the engine's packaged manifest, with no asserted deployment commit.
    payload = capabilities_payload()
    # When the standard-library SDK parses it, then versions stay exactly server-reported.
    parsed = CapabilitySet.from_payload(payload)
    assert parsed.server_build is None
    assert parsed.receipt_schema_version == payload["receipt_schema_version"]
    assert parsed.evidence_schema_version == payload["evidence_schema_version"]
    assert parsed.mcp_toolset_version == payload["mcp_toolset_version"]
    assert parsed.supported_mcp_protocols == tuple(payload["supported_mcp_protocols"])


def test_engine_collection_modes_survive_mcp_and_sdk_without_execution_inference() -> None:
    # Given different admission and actual diagnostic values: the admission field is not a proof.
    payload = build_n8n_node_output(
        created_payload={
            "run_id": "r1",
            "status": "QUEUED",
            "synthesis_mode_requested": "auto",
            "synthesis_mode_used": "stable_hybrid",
            "auto_synthesis_reason": "ensemble",
        },
        run_payload={
            "run_id": "r1",
            "status": "SUCCEEDED",
            "result_status": "DEGRADED",
            "synthesis_mode": "robust",
            "diagnostics": {"mode_used": "robust", "private": True},
        },
    )
    # When the MCP public view and SDK consume the actual engine helper output.
    projected = project_tool_output("adaptorch_run", payload)
    assert projected is not None
    run = Run.from_payload(projected)
    # Then observed fields survive, private diagnostics do not, and no success is invented.
    assert run.synthesis_mode_requested == "auto"
    assert run.synthesis_mode_used == "stable_hybrid"
    assert run.result_status == "DEGRADED"
    assert "diagnostics" not in projected
