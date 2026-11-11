"""Registry introspection without credentials, with tool calls still authenticated."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from adaptorch_mcp import __version__, thin_runtime
from adaptorch_mcp.public_schema import project_remote_tool
from adaptorch_mcp.thin_remote import REMOTE_TOOL_NAMES, RemoteMCPServer, discovery_catalog

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
CLIENT_SRC = Path(__file__).resolve().parents[2] / "adaptorch-client" / "src"
_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "registry-probe", "version": "0"},
    },
}


def _stdio(messages: list[dict[str, Any]], env: dict[str, str]) -> list[dict[str, Any]]:
    stdin = "".join(json.dumps(message) + "\n" for message in messages)
    completed = subprocess.run(
        [sys.executable, "-m", "adaptorch_mcp", "--transport", "stdio"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=True,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def _clean_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ADAPTORCH_") and not key.endswith("_API_KEY")
    }
    env["PYTHONPATH"] = os.pathsep.join([str(PACKAGE_SRC), str(CLIENT_SRC)])
    return env


def test_stdio_without_token_answers_introspection_from_the_pinned_catalog() -> None:
    responses = _stdio(
        [
            _INITIALIZE,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        ],
        _clean_env(),
    )

    assert [item["id"] for item in responses] == [1, 2, 3]
    initialized = responses[0]["result"]
    assert initialized["protocolVersion"] == "2025-06-18"
    assert initialized["serverInfo"] == {"name": "adaptorch-mcp", "version": __version__}
    assert initialized["capabilities"] == {"tools": {"listChanged": False}}
    assert tuple(tool["name"] for tool in responses[1]["result"]["tools"]) == REMOTE_TOOL_NAMES
    assert responses[2]["result"] == {}


@pytest.mark.parametrize(
    "message",
    [
        {"method": "tools/call", "params": {"name": "adaptorch_usage", "arguments": {}}},
        {"method": "resources/read", "params": {"uri": "adaptorch://server-info"}},
    ],
)
def test_discovery_mode_refuses_authenticated_requests_without_a_network_call(
    message: dict[str, Any],
) -> None:
    server = RemoteMCPServer.discovery_only()

    response = server.handle_message({"jsonrpc": "2.0", "id": 7, **message})

    assert response == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {"code": -32001, "message": "ADAPTORCH_CONTROL_PLANE_TOKEN is not configured"},
    }


def test_discovery_mode_lists_no_resources_or_prompts() -> None:
    server = RemoteMCPServer.discovery_only()

    for method, key in (
        ("resources/list", "resources"),
        ("resources/templates/list", "resourceTemplates"),
        ("prompts/list", "prompts"),
    ):
        response = server.handle_message({"jsonrpc": "2.0", "id": 4, "method": method})
        assert response == {"jsonrpc": "2.0", "id": 4, "result": {key: []}}


def test_discovery_initialize_offers_a_supported_protocol_for_unknown_requests() -> None:
    server = RemoteMCPServer.discovery_only()
    message = {**_INITIALIZE, "params": {**_INITIALIZE["params"], "protocolVersion": "1999-01-01"}}

    response = server.handle_message(message)

    assert response is not None
    assert response["result"]["protocolVersion"] == "2025-06-18"


def test_pinned_catalog_is_the_public_projection_of_the_remote_tools() -> None:
    tools = discovery_catalog()

    assert tuple(tool["name"] for tool in tools) == REMOTE_TOOL_NAMES
    for tool in tools:
        assert project_remote_tool(tool) == tool
    run_properties = tools[0]["inputSchema"]["properties"]
    assert not {"trace", "verification_commands"} & set(run_properties)


def test_catalog_is_returned_as_a_copy() -> None:
    discovery_catalog()[0]["name"] = "mutated"

    assert discovery_catalog()[0]["name"] == "adaptorch_run"


def test_http_transport_still_requires_the_upstream_token() -> None:
    with pytest.raises(ValueError, match="ADAPTORCH_CONTROL_PLANE_TOKEN is required"):
        thin_runtime.run_remote_main(["--transport", "http"], env={})


_LIFECYCLE_TOOLS = ("adaptorch_run", "adaptorch_get_run", "adaptorch_get_artifacts")


def _described_paths(schema: dict[str, Any], prefix: str = "") -> list[tuple[str, bool]]:
    found: list[tuple[str, bool]] = []
    for key, value in schema.get("properties", {}).items():
        found.append((prefix + key, bool(str(value.get("description", "")).strip())))
        if value.get("type") == "object":
            found.extend(_described_paths(value, prefix + key + "."))
    return found


@pytest.mark.parametrize("name", _LIFECYCLE_TOOLS)
def test_registry_sees_every_lifecycle_argument_described(name: str) -> None:
    tool = next(t for t in discovery_catalog() if t["name"] == name)

    assert [path for path, ok in _described_paths(tool["inputSchema"]) if not ok] == []
    assert any(other in tool["description"] for other in _LIFECYCLE_TOOLS if other != name)


def test_catalog_descriptions_only_name_arguments_the_catalog_offers() -> None:
    get_run = next(t for t in discovery_catalog() if t["name"] == "adaptorch_get_run")

    if "include_output" not in get_run["inputSchema"]["properties"]:
        assert "include_output" not in get_run["description"]
