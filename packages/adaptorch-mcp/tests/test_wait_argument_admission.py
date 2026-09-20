"""Reject unusable wait controls before any potentially billable backend call."""

from __future__ import annotations

import math
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
@pytest.mark.parametrize("value", [True, 0, -1, math.nan, math.inf, 10**400])
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


@pytest.mark.parametrize("profile", [REMOTE_EXPOSURE_PROFILE, FULL_EXPOSURE_PROFILE])
def test_resume_run_id_cannot_mix_submission_options(profile: ExposureProfile) -> None:
    """A resume call carrying prompt/payload is refused before any HTTP work."""
    backend = FakeBackend()
    server = HardenedMCPServer(backend=backend, exposure_profile=profile)
    for arguments in (
        {"resume_run_id": "r1", "prompt": "new task"},
        {"resume_run_id": "r1", "payload": {"subtasks": []}},
        {"resume_run_id": "r1", "idempotency_key": "task-00000000-aa"},
        {"resume_run_id": "r1", "model": "x"},
    ):
        result = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "adaptorch_run", "arguments": arguments},
            }
        )
        assert result is not None and result["error"]["code"] == -32602, arguments


def test_resume_run_id_rejects_a_backend_that_cannot_collect() -> None:
    """resume_run_id requires the connector backend, never a silent fallback."""
    server = HardenedMCPServer(backend=FakeBackend(), exposure_profile=REMOTE_EXPOSURE_PROFILE)
    result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "adaptorch_run", "arguments": {"resume_run_id": "r1"}},
        }
    )
    assert result is not None and result["error"]["code"] == -32602
