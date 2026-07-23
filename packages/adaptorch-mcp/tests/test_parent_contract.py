from __future__ import annotations

import copy
from typing import Any

import pytest
from adaptorch.mcp_server import AdaptOrchMCPServer

from adaptorch_mcp.hardening import HardenedMCPServer
from mcp_test_support import FakeBackend


@pytest.mark.parametrize(
    "input_schema",
    [
        None,
        "not-a-schema",
        {"type": "object", "properties": {}, "additionalProperties": True},
        {"type": "object", "additionalProperties": False},
        {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": "run_id",
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["missing"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"run_id": "string"},
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {1: {"type": "string"}},
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"run_id": {"type": "definitely-not-json-schema"}},
            "additionalProperties": False,
        },
    ],
)
def test_remote_profile_rejects_malformed_parent_tool_schema(
    monkeypatch: pytest.MonkeyPatch,
    input_schema: Any,
) -> None:
    tools = copy.deepcopy(AdaptOrchMCPServer._tool_schemas())
    run_tool = next(tool for tool in tools if tool["name"] == "adaptorch_run")
    run_tool["inputSchema"] = input_schema
    monkeypatch.setattr(
        AdaptOrchMCPServer,
        "_tool_schemas",
        staticmethod(lambda: tools),
    )

    with pytest.raises(RuntimeError, match="parent MCP tool"):
        HardenedMCPServer(backend=FakeBackend(), exposure_profile="remote")


def test_remote_get_run_descriptor_has_closed_correctness_wall_output_schema() -> None:
    server = HardenedMCPServer(backend=FakeBackend(), exposure_profile="remote")

    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )

    assert response is not None
    get_run = next(
        tool for tool in response["result"]["tools"] if tool["name"] == "adaptorch_get_run"
    )
    assert get_run["annotations"] == {
        "title": "Get AdaptOrch run summary",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    output_schema = get_run["outputSchema"]
    assert output_schema["type"] == "object"
    assert output_schema["additionalProperties"] is False
    assert output_schema["required"] == ["run_id", "status"]
    wall_schema = output_schema["properties"]["correctness_wall"]
    assert wall_schema["type"] == ["object", "null"]
    assert wall_schema["additionalProperties"] is False
    assert wall_schema["properties"]["blockers"]["maxItems"] == 16
    assert wall_schema["properties"]["blockers"]["items"]["maxLength"] == 256
    assert wall_schema["properties"]["correctness_claim"] == {"const": False}


def test_remote_descriptor_drops_unknown_parent_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = copy.deepcopy(AdaptOrchMCPServer._tool_schemas())
    get_run = next(tool for tool in tools if tool["name"] == "adaptorch_get_run")
    get_run["_meta"] = {"private": True}
    get_run["inputSchema"]["x-private"] = "drop-me"
    get_run["inputSchema"]["properties"]["run_id"]["x-private"] = "drop-me"
    monkeypatch.setattr(
        AdaptOrchMCPServer,
        "_tool_schemas",
        staticmethod(lambda: tools),
    )

    server = HardenedMCPServer(backend=FakeBackend(), exposure_profile="remote")
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )

    assert response is not None
    projected = next(
        tool for tool in response["result"]["tools"] if tool["name"] == "adaptorch_get_run"
    )
    assert set(projected) == {
        "name",
        "description",
        "annotations",
        "inputSchema",
        "outputSchema",
    }
    assert "x-private" not in projected["inputSchema"]
    assert "x-private" not in projected["inputSchema"]["properties"]["run_id"]


def test_full_profile_does_not_project_parent_input_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = copy.deepcopy(AdaptOrchMCPServer._tool_schemas())
    run_tool = next(tool for tool in tools if tool["name"] == "adaptorch_run")
    run_tool["inputSchema"] = "parent-owned-schema"
    monkeypatch.setattr(
        AdaptOrchMCPServer,
        "_tool_schemas",
        staticmethod(lambda: tools),
    )

    server = HardenedMCPServer(backend=FakeBackend(), exposure_profile="full")
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )

    assert response is not None
    run_tool = next(
        tool for tool in response["result"]["tools"] if tool["name"] == "adaptorch_run"
    )
    get_run = next(
        tool for tool in response["result"]["tools"] if tool["name"] == "adaptorch_get_run"
    )
    assert run_tool["inputSchema"] == "parent-owned-schema"
    assert "outputSchema" not in get_run
