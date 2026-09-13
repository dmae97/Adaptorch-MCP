"""The public wrapper preserves declared observations, not private execution state."""

from __future__ import annotations

import json
from typing import Any

import pytest

from adaptorch_mcp.hardening import HardenedMCPServer
from adaptorch_mcp.output_schema import project_tool_output
from adaptorch_mcp.response_policy import sanitize_tool_response
from adaptorch_mcp.security_policy import REMOTE_EXPOSURE_PROFILE
from mcp_test_support import FakeBackend


def _response(text: str, flag: object = False) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": text}],
            "isError": flag,
        },
    }


@pytest.mark.parametrize("tool", ["adaptorch_run", "adaptorch_get_run", "adaptorch_cancel_run"])
def test_admission_modes_survive_every_run_projection(tool: str) -> None:
    payload = {
        "run_id": "r1",
        "status": "SUCCEEDED",
        "result_status": "DEGRADED",
        "synthesis_mode_requested": "auto",
        "synthesis_mode_used": "stable_hybrid",
        "auto_synthesis_reason": "ensemble",
        "diagnostics": {"private": "omit"},
    }
    projected = project_tool_output(tool, payload)
    assert projected is not None
    assert projected["synthesis_mode_requested"] == "auto"
    assert projected["synthesis_mode_used"] == "stable_hybrid"
    assert projected["auto_synthesis_reason"] == "ensemble"
    assert projected["result_status"] == "DEGRADED" and "diagnostics" not in projected


@pytest.mark.parametrize(
    "key,value",
    [
        ("synthesis_mode_used", True),
        ("model", 42),
        ("evaluation_status", False),
        ("consistency", True),
        ("consistency", float("nan")),
        ("consistency", 2),
        ("duration_ms", -1),
        ("duration_ms", True),
        ("duration_ms", 0.5),
    ],
)
@pytest.mark.parametrize(
    "tool", ["adaptorch_run", "adaptorch_get_run", "adaptorch_cancel_run", "adaptorch_list_runs"]
)
def test_bad_observations_fail_in_direct_and_list_containers(
    tool: str, key: str, value: Any
) -> None:
    run = {"run_id": "r1", "status": "SUCCEEDED", key: value}
    payload = {"items": [run]} if tool == "adaptorch_list_runs" else run
    assert project_tool_output(tool, payload) is None


@pytest.mark.parametrize(
    "text",
    [
        '{"run_id":"r1","run_id":"r2","status":"SUCCEEDED"}',
        '{"run_id":"r1","status":"SUCCEEDED","consistency":NaN}',
        '{"run_id":"r1","status":"SUCCEEDED","private":{"same":1,"same":2}}',
    ],
)
def test_ambiguous_json_is_not_projected_as_success(text: str) -> None:
    result = sanitize_tool_response(_response(text), tool_name="adaptorch_get_run")
    assert result["result"]["isError"] is True
    assert "r1" not in result["result"]["content"][0]["text"]


@pytest.mark.parametrize("flag", ["true", "false", 0, 1, None])
def test_nonboolean_error_flag_is_a_format_failure(flag: object) -> None:
    result = sanitize_tool_response(
        _response(json.dumps({"run_id": "r1", "status": "SUCCEEDED"}), flag),
        tool_name="adaptorch_get_run",
    )
    assert result["result"]["isError"] is True


def test_remote_reader_rejects_a_foreign_run_before_exposing_it() -> None:
    class WrongRun(FakeBackend):
        def get_run(self, run_id: str) -> dict[str, Any]:
            return {"run_id": "another-run", "status": "SUCCEEDED", "model": "private"}

    server = HardenedMCPServer(backend=WrongRun(), exposure_profile=REMOTE_EXPOSURE_PROFILE)
    result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "adaptorch_get_run", "arguments": {"run_id": "expected"}},
        }
    )
    assert result is not None and result["result"]["isError"] is True
    assert "private" not in json.dumps(result)


def test_reader_binding_uses_the_parent_normalized_request_subject() -> None:
    server = HardenedMCPServer(backend=FakeBackend(), exposure_profile=REMOTE_EXPOSURE_PROFILE)
    result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "adaptorch_get_run", "arguments": {"run_id": "  r1  "}},
        }
    )
    assert result is not None and result["result"]["isError"] is False
    assert result["result"]["structuredContent"]["run_id"] == "r1"
