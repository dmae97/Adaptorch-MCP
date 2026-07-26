"""Tenant usage awareness through the hardened remote MCP surface.

`adaptorch_usage` reads the caller's own usage window from the control plane. The
tenant is resolved server-side from the API key, so the tool takes no arguments
and the wrapper must not let a client widen the scope.
"""

from __future__ import annotations

import json
from typing import Any

from adaptorch_mcp.diagnostics import EXPECTED_CORE_TOOLS
from adaptorch_mcp.hardening import REMOTE_TOOL_NAMES, HardenedMCPServer
from adaptorch_mcp.output_schema import project_tool_output
from adaptorch_mcp.security_policy import REMOTE_EXPOSURE_PROFILE
from mcp_test_support import ControlPlaneFakeBackend

USAGE_PAYLOAD = {
    "tenant_id": "tenant-1",
    "plan_level": "starter",
    "period": "2026-07",
    "used": 120,
    "limit": 1000,
    "remaining": 880,
    "usage_percentage": 12,
}


def _remote_server(responses: dict[str, dict[str, Any]] | None = None) -> HardenedMCPServer:
    return HardenedMCPServer(
        backend=ControlPlaneFakeBackend(responses or {"/v1/usage": USAGE_PAYLOAD}),
        exposure_profile=REMOTE_EXPOSURE_PROFILE,
    )


def _call(server: HardenedMCPServer, arguments: dict[str, Any]) -> dict[str, Any]:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "adaptorch_usage", "arguments": arguments},
        }
    )
    assert response is not None
    return response


def test_usage_tool_is_exposed_in_the_default_remote_profile() -> None:
    assert "adaptorch_usage" in REMOTE_TOOL_NAMES
    assert "adaptorch_usage" in EXPECTED_CORE_TOOLS

    response = _remote_server().handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )
    assert response is not None
    tools = {tool["name"]: tool for tool in response["result"]["tools"]}

    assert "adaptorch_usage" in tools
    schema = tools["adaptorch_usage"]["inputSchema"]
    assert schema["properties"] == {}
    assert schema["additionalProperties"] is False
    assert tools["adaptorch_usage"]["annotations"]["readOnlyHint"] is True


def test_usage_call_returns_the_projected_tenant_window() -> None:
    server = _remote_server()

    response = _call(server, {})

    assert "error" not in response
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload == USAGE_PAYLOAD
    backend = server._backend
    assert isinstance(backend, ControlPlaneFakeBackend)
    assert backend.requests == [("GET", "/v1/usage")]


def test_usage_call_rejects_a_client_supplied_tenant() -> None:
    server = _remote_server()

    response = _call(server, {"tenant_id": "other-tenant"})

    assert response["error"]["code"] == -32602
    backend = server._backend
    assert isinstance(backend, ControlPlaneFakeBackend)
    assert backend.requests == []


def test_usage_projection_drops_unknown_fields_and_requires_counters() -> None:
    projected = project_tool_output(
        "adaptorch_usage",
        {**USAGE_PAYLOAD, "internal_counter_source": "redis", "diagnostics": {"key": "value"}},
    )

    assert projected == USAGE_PAYLOAD

    assert project_tool_output("adaptorch_usage", {"tenant_id": "tenant-1"}) is None
    assert project_tool_output("adaptorch_usage", {"used": {"nested": 1}, "limit": 1000}) is None


def test_usage_response_is_sanitized_when_the_control_plane_adds_internals() -> None:
    server = _remote_server(
        {
            "/v1/usage": {
                **USAGE_PAYLOAD,
                "counter_source": "redis",
                "supabase_row": {"id": 9},
            }
        }
    )

    response = _call(server, {})

    text = response["result"]["content"][0]["text"]
    assert "counter_source" not in text
    assert "supabase_row" not in text
    assert json.loads(text) == USAGE_PAYLOAD
