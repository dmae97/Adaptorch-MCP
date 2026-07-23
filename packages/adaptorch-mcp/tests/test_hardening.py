from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from adaptorch_mcp.hardening import (
    FULL_EXPOSURE_PROFILE,
    REMOTE_EXPOSURE_PROFILE,
    REMOTE_TOOL_NAMES,
    HardenedMCPServer,
    resolve_exposure_profile,
    validate_control_plane_url,
    validate_http_binding,
    validate_parent_tools,
    validate_separate_tokens,
)
from mcp_test_support import FakeBackend

_FakeBackend = FakeBackend


def _request(
    method: str,
    *,
    request_id: int = 1,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = dict(params)
    return payload


def _tools(server: HardenedMCPServer) -> tuple[Mapping[str, Any], ...]:
    response = server.handle_message(_request("tools/list"))
    assert response is not None
    return tuple(response["result"]["tools"])


def _tool_names(server: HardenedMCPServer) -> tuple[str, ...]:
    return tuple(tool["name"] for tool in _tools(server))


def _call_tool(
    server: HardenedMCPServer,
    name: str,
    arguments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    response = server.handle_message(
        _request(
            "tools/call",
            params={"name": name, "arguments": dict(arguments or {})},
        )
    )
    assert response is not None
    return response


def test_exposure_profile_defaults_remote_and_rejects_unknown() -> None:
    assert resolve_exposure_profile({}) == REMOTE_EXPOSURE_PROFILE
    assert resolve_exposure_profile({"ADAPTORCH_MCP_EXPOSURE_PROFILE": " full "}) == (
        FULL_EXPOSURE_PROFILE
    )
    with pytest.raises(ValueError, match="ADAPTORCH_MCP_EXPOSURE_PROFILE"):
        resolve_exposure_profile({"ADAPTORCH_MCP_EXPOSURE_PROFILE": "debug"})


@pytest.mark.parametrize(
    "url",
    [
        "https://adaptorch.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://127.42.0.9:8000",
        "http://[::1]:8000",
    ],
)
def test_control_plane_url_allows_https_and_loopback_http(url: str) -> None:
    assert validate_control_plane_url(url, allow_insecure=False) == url


def test_control_plane_url_rejects_plaintext_remote_and_userinfo() -> None:
    for url in (
        "http://api.example.com",
        "http://localhost.evil.example",
        "https://user:pass@example.com",
    ):
        with pytest.raises(ValueError):
            validate_control_plane_url(url, allow_insecure=False)

    assert validate_control_plane_url(
        "http://dev.example.com", allow_insecure=True
    ) == "http://dev.example.com"


def test_http_binding_is_loopback_only() -> None:
    for host in ("localhost", "127.0.0.1", "127.8.9.10", "::1"):
        validate_http_binding(host)
    for host in ("0.0.0.0", "example.com", "localhost.evil"):
        with pytest.raises(ValueError, match="loopback"):
            validate_http_binding(host)


def test_http_tokens_must_be_present_and_distinct() -> None:
    validate_separate_tokens("upstream-token", "client-token")
    for upstream, client in (("", "client"), ("upstream", ""), ("same", " same ")):
        with pytest.raises(ValueError):
            validate_separate_tokens(upstream, client)


def test_remote_profile_uses_strict_tool_allowlist_and_blocks_oracles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADAPTORCH_MCP_ALLOW_VERIFICATION_COMMANDS", "1")
    server = HardenedMCPServer(backend=_FakeBackend(), exposure_profile="remote")

    assert _tool_names(server) == REMOTE_TOOL_NAMES
    for blocked in ("adaptorch_route_topology", "adaptorch_get_traces", "future_parent_tool"):
        response = _call_tool(server, blocked)
        assert response["error"]["code"] == -32601

    trace_response = _call_tool(server, "adaptorch_run", {"prompt": "hello", "trace": True})
    assert trace_response["error"]["code"] == -32602
    command_response = _call_tool(
        server,
        "adaptorch_run",
        {"prompt": "hello", "verification_commands": ["pytest"]},
    )
    assert command_response["error"]["code"] == -32602
    nested_command_response = _call_tool(
        server,
        "adaptorch_run",
        {
            "payload": {
                "prompt": "hello",
                "metadata": {"mcp": {"verification_commands": ["pytest"]}},
            }
        },
    )
    assert nested_command_response["error"]["code"] == -32602


def test_remote_profile_projects_run_schema_and_rejects_unknown_arguments() -> None:
    server = HardenedMCPServer(backend=_FakeBackend(), exposure_profile="remote")
    run_tool = next(tool for tool in _tools(server) if tool["name"] == "adaptorch_run")

    properties = run_tool["inputSchema"]["properties"]
    assert "trace" not in properties
    assert "verification_commands" not in properties
    assert run_tool["inputSchema"]["additionalProperties"] is False

    response = _call_tool(server, "adaptorch_run", {"prompt": "hello", "future": True})
    assert response["error"]["code"] == -32602

    malformed = server.handle_message(
        _request(
            "tools/call",
            params={"name": "adaptorch_server_metrics", "arguments": []},
        )
    )
    assert malformed is not None
    assert malformed["error"]["code"] == -32602


def test_remote_capabilities_match_facade_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADAPTORCH_MCP_ALLOW_VERIFICATION_COMMANDS", "1")
    server = HardenedMCPServer(backend=_FakeBackend(), exposure_profile="remote")

    response = _call_tool(server, "adaptorch_capabilities")
    payload = json.loads(response["result"]["content"][0]["text"])

    assert payload["server_capabilities"]["completions"] is False
    assert payload["server_capabilities"]["verification_commands_enabled"] is False


def test_remote_profile_hides_sensitive_resources_and_completions() -> None:
    server = HardenedMCPServer(backend=_FakeBackend(), exposure_profile="remote")

    resources = server.handle_message(_request("resources/list"))
    assert resources is not None
    assert {item["uri"] for item in resources["result"]["resources"]} == {
        "adaptorch://server-info",
        "adaptorch://plans/cloud",
    }

    templates = server.handle_message(_request("resources/templates/list"))
    assert templates == {"jsonrpc": "2.0", "id": 1, "result": {"resourceTemplates": []}}

    server_info = server.handle_message(
        _request("resources/read", params={"uri": "adaptorch://server-info"})
    )
    assert server_info is not None
    server_payload = json.loads(server_info["result"]["contents"][0]["text"])
    assert "completions" not in server_payload["capabilities"]

    plan_catalog = server.handle_message(
        _request("resources/read", params={"uri": "adaptorch://plans/cloud"})
    )
    assert plan_catalog is not None
    plan_payload = json.loads(plan_catalog["result"]["contents"][0]["text"])
    assert plan_payload["schemaVersion"] == "adaptorch.cloud_plan_catalog.v1"

    blocked = server.handle_message(
        _request("resources/read", params={"uri": "adaptorch://runs/r1/summary"})
    )
    assert blocked is not None
    assert blocked["error"]["code"] == -32601

    completion = server.handle_message(_request("completion/complete", params={}))
    assert completion is not None
    assert completion["error"]["code"] == -32601


def test_remote_profile_redacts_algorithm_diagnostics_and_suppresses_events() -> None:
    server = HardenedMCPServer(backend=_FakeBackend(), exposure_profile="remote")
    events: list[Mapping[str, Any]] = []
    server.set_notification_sink(events.append)

    response = _call_tool(server, "adaptorch_get_run", {"run_id": "r1"})
    payload = json.loads(response["result"]["content"][0]["text"])

    assert payload == {"run_id": "r1", "status": "SUCCEEDED", "topology": "hybrid"}

    artifact_response = _call_tool(server, "adaptorch_get_artifacts", {"run_id": "r1"})
    artifact_payload = json.loads(artifact_response["result"]["content"][0]["text"])
    assert artifact_payload == {"run_id": "r1", "artifacts": []}
    assert events == []


@pytest.mark.parametrize(
    "method",
    ("tools/list", "resources/list", "resources/templates/list"),
)
def test_remote_profile_preserves_parent_errors_for_malformed_list_requests(
    method: str,
) -> None:
    server = HardenedMCPServer(backend=_FakeBackend(), exposure_profile="remote")

    message = _request(method)
    message["jsonrpc"] = "1.0"

    response = server.handle_message(message)

    assert response is not None
    assert "error" in response
    assert response["error"]["code"] != -32603


def test_direct_server_construction_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="exposure profile"):
        HardenedMCPServer(backend=_FakeBackend(), exposure_profile="debug")


def test_full_profile_preserves_parent_tool_surface() -> None:
    server = HardenedMCPServer(backend=_FakeBackend(), exposure_profile="full")

    names = _tool_names(server)
    assert "adaptorch_route_topology" in names
    assert "adaptorch_get_traces" in names


def test_parent_contract_validation_fails_closed() -> None:
    validate_parent_tools(REMOTE_TOOL_NAMES, REMOTE_EXPOSURE_PROFILE)
    with pytest.raises(RuntimeError, match="missing required tools"):
        validate_parent_tools(("adaptorch_run",), REMOTE_EXPOSURE_PROFILE)
