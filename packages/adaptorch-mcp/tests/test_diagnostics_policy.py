from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_control_plane_token_format_recognition_matches_dashboard_contract() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics

    for token in ("ado_live_abc123", "ado_test_abc123", "ak_legacy123"):
        payload = collect_diagnostics({"ADAPTORCH_CONTROL_PLANE_TOKEN": token})
        status = payload["environment"]["tokens"]["ADAPTORCH_CONTROL_PLANE_TOKEN"]
        assert status == {"set": True, "formatRecognized": True}
        assert token not in str(payload)

    # Fake header-only JWT shape; not a credential.
    jwt_like = collect_diagnostics(
        {"ADAPTORCH_CONTROL_PLANE_TOKEN": "eyJhbGciOiJIUzI1NiJ9.x.y"}  # gitleaks:allow
    )
    assert jwt_like["environment"]["tokens"]["ADAPTORCH_CONTROL_PLANE_TOKEN"] == {
        "set": True,
        "formatRecognized": False,
    }

    unset = collect_diagnostics({})
    assert unset["environment"]["tokens"]["ADAPTORCH_CONTROL_PLANE_TOKEN"] == {"set": False}
    http_token = collect_diagnostics({"ADAPTORCH_MCP_HTTP_AUTH_TOKEN": "ado_live_client"})
    assert http_token["environment"]["tokens"]["ADAPTORCH_MCP_HTTP_AUTH_TOKEN"] == {"set": True}


def test_diagnostics_fail_closed_for_remote_plaintext_control_plane() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics

    payload = collect_diagnostics(
        {"ADAPTORCH_CONTROL_PLANE_BASE_URL": "http://api.example.com"}
    )

    assert payload["controlPlane"]["policyValid"] is False
    assert payload["security"]["remoteControlPlaneRequiresHttps"] is True
    assert payload["security"]["insecureControlPlaneAllowed"] is False
    assert payload["ok"] is False


def test_diagnostics_reports_hardened_posture_without_token_length() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics
    from adaptorch_mcp.hardening import REMOTE_TOOL_NAMES

    payload = collect_diagnostics({"ADAPTORCH_CONTROL_PLANE_TOKEN": "ado_live_secret"})

    assert payload["environment"]["tokens"]["ADAPTORCH_CONTROL_PLANE_TOKEN"] == {
        "set": True,
        "formatRecognized": True,
    }
    assert payload["security"] == {
        "exposureProfile": "remote",
        "profileValid": True,
        "algorithmExecutionBoundary": "control-plane",
        "localAlgorithmOraclesExposed": False,
        "remoteControlPlaneRequiresHttps": True,
        "insecureControlPlaneAllowed": False,
        "httpTokensMustBeDistinct": True,
    }
    assert payload["expectedTools"] == list(REMOTE_TOOL_NAMES)


def test_diagnostics_full_profile_is_explicit_and_invalid_profile_fails_closed() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics
    from adaptorch_mcp.hardening import REMOTE_TOOL_NAMES

    full = collect_diagnostics({"ADAPTORCH_MCP_EXPOSURE_PROFILE": "full"})
    assert full["security"]["localAlgorithmOraclesExposed"] is True
    assert full["security"]["algorithmExecutionBoundary"] == "mixed-local-and-control-plane"
    assert "adaptorch_route_topology" in full["expectedTools"]
    assert "adaptorch_get_traces" in full["expectedTools"]

    invalid = collect_diagnostics({"ADAPTORCH_MCP_EXPOSURE_PROFILE": "debug"})
    assert invalid["ok"] is False
    assert invalid["security"]["profileValid"] is False
    assert invalid["expectedTools"] == list(REMOTE_TOOL_NAMES)
