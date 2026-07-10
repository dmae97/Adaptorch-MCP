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
