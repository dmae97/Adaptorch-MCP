"""Reject unusable wait controls before any potentially billable backend call."""

from __future__ import annotations

from typing import Any

import pytest

from adaptorch_mcp.hardening import HardenedMCPServer
from adaptorch_mcp.security_policy import (
    FULL_EXPOSURE_PROFILE,
    REMOTE_EXPOSURE_PROFILE,
    ExposureProfile,
)
from mcp_test_support import FakeBackend


@pytest.mark.parametrize("profile", [REMOTE_EXPOSURE_PROFILE, FULL_EXPOSURE_PROFILE])
@pytest.mark.parametrize("field", ["timeout_seconds", "poll_interval_seconds"])
@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), 10**400])
def test_invalid_wait_controls_are_refused_before_submission(
    profile: ExposureProfile,
    field: str,
    value: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeBackend()
    calls: list[str] = []

    def forbidden(**kwargs: Any) -> dict[str, Any]:
        calls.append("submitted")
        return {"run_id": "r1", "status": "SUCCEEDED"}

    monkeypatch.setattr(backend, "run_task_and_collect", forbidden)
    server = HardenedMCPServer(backend=backend, exposure_profile=profile)
    result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "adaptorch_run", "arguments": {"prompt": "fixture", field: value}},
        }
    )
    assert calls == []
    assert result is not None and result["error"]["code"] == -32602
