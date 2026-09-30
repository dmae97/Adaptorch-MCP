"""Remote remediation may describe validation, never echo arbitrary input."""

from __future__ import annotations

import json

import pytest

from adaptorch_mcp.control_plane_backend import SafeControlPlaneConnector
from adaptorch_mcp.hardening import HardenedMCPServer
from adaptorch_mcp.response_policy import sanitize_tool_response
from test_control_plane_backend import PAYLOAD, PROVIDER_KEY, TENANT_KEY, Wire
from test_control_plane_backend import backend as backend
from test_control_plane_backend import wire as wire


@pytest.mark.parametrize("status", [400, 422])
def test_remote_validation_remediation_is_safe_and_not_retryable(
    backend: SafeControlPlaneConnector, wire: Wire, status: int
) -> None:
    wire.replies = [
        (status, json.dumps({"detail": "invalid " + PROVIDER_KEY + TENANT_KEY}).encode())
    ]
    server = HardenedMCPServer(backend=backend, exposure_profile="remote")
    result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "adaptorch_run",
                "arguments": {"payload": PAYLOAD, "wait_for_terminal": False},
            },
        }
    )
    assert result is not None and result["result"]["isError"] is True
    rejected = json.loads(result["result"]["content"][0]["text"])
    assert rejected["error"] == "CONTROL_PLANE_REJECTED"
    assert rejected["status_code"] == status
    assert rejected["retryable"] is False
    assert "Check" in rejected["message"]
    assert "invalid " not in rejected["message"]
    assert "X-Provider" in rejected["message"]
    assert TENANT_KEY not in json.dumps(result) and PROVIDER_KEY not in json.dumps(result)
    assert rejected["new_run_safe"] is False
    assert len(wire.calls) == 1


@pytest.mark.parametrize("retryable", [True, False, "false", 1, None])
def test_rejected_retryable_is_a_strict_boolean(retryable: object) -> None:
    decoded = {
        "error": "CONTROL_PLANE_REJECTED",
        "status_code": 429,
        "message": "private",
        "retryable": retryable,
    }
    result = sanitize_tool_response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"isError": True, "content": [{"type": "text", "text": json.dumps(decoded)}]},
        },
        tool_name="adaptorch_run",
    )
    body = json.loads(result["result"]["content"][0]["text"])
    if isinstance(retryable, bool):
        assert body["retryable"] is retryable
        assert "private" not in json.dumps(body)
    else:
        assert body == {"error": "unsupported tool response format"}
