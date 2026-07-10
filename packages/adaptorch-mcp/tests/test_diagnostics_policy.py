from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_diagnostics_fail_closed_for_remote_plaintext_control_plane() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics

    payload = collect_diagnostics(
        {"ADAPTORCH_CONTROL_PLANE_BASE_URL": "http://api.example.com"}
    )

    assert payload["controlPlane"]["policyValid"] is False
    assert payload["security"]["remoteControlPlaneRequiresHttps"] is True
    assert payload["security"]["insecureControlPlaneAllowed"] is False
    assert payload["ok"] is False
