"""Remote-only JSON-RPC MCP client facade with no private engine imports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from functools import cache
from importlib.resources import files
from threading import TIMEOUT_MAX
from typing import Any, Final, Protocol, cast

from adaptorch_client.config import ClientConfig
from adaptorch_client.errors import AdaptOrchAPIError
from adaptorch_client.provider import ProviderCredential
from adaptorch_client.transport import HTTPTransport, RequestSpec
from adaptorch_mcp import __version__
from adaptorch_mcp.public_schema import ParentContractError, project_remote_tool
from adaptorch_mcp.response_policy import sanitize_resource_response, sanitize_tool_response

REMOTE_TOOL_NAMES: Final = (
    "adaptorch_run",
    "adaptorch_get_run",
    "adaptorch_get_artifacts",
    "adaptorch_list_runs",
    "adaptorch_cancel_run",
    "adaptorch_server_metrics",
    "adaptorch_capabilities",
    "adaptorch_usage",
    "adaptorch_plan_catalog",
)
CANDIDATE_TOOL_NAMES: Final = ("adaptorch_verify_candidate", "adaptorch_get_verification_report")
_REMOTE_ACCEPTED_TOOLS: Final = REMOTE_TOOL_NAMES + CANDIDATE_TOOL_NAMES
_REMOTE_RESOURCES: Final = frozenset({"adaptorch://server-info", "adaptorch://plans/cloud"})
_FORWARD_METHODS: Final = frozenset(
    {
        "initialize",
        "ping",
        "tools/list",
        "tools/call",
        "resources/list",
        "resources/read",
        "resources/templates/list",
        "prompts/list",
        "prompts/get",
        "logging/setLevel",
    }
)


_SUPPORTED_PROTOCOLS: Final = ("2025-06-18", "2025-03-26", "2024-11-05")
_MISSING_TOKEN: Final = "ADAPTORCH_CONTROL_PLANE_TOKEN is not configured"
_DISCOVERY_EMPTY_LISTS: Final = {
    "resources/list": "resources",
    "resources/templates/list": "resourceTemplates",
    "prompts/list": "prompts",
}


@cache
def _load_catalog() -> tuple[dict[str, Any], ...]:
    text = files("adaptorch_mcp").joinpath("remote_tool_catalog.json").read_text("utf-8")
    tools = json.loads(text)["tools"]
    if tuple(tool["name"] for tool in tools) != REMOTE_TOOL_NAMES:
        raise ParentContractError("discovery catalog differs from the remote tool set")
    return tuple(tools)


def discovery_catalog() -> list[dict[str, Any]]:
    """Return the pinned public tool list served before credentials are configured."""
    return deepcopy(list(_load_catalog()))


class RemoteTransport(Protocol):
    def request(self, spec: RequestSpec) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


def _error(message: Mapping[str, Any], code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": code, "message": text}}


def _params(message: Mapping[str, Any]) -> Mapping[str, Any]:
    value = message.get("params")
    return value if isinstance(value, Mapping) else {}


def _arguments(message: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _params(message).get("arguments")
    return value if isinstance(value, Mapping) else {}


class RemoteMCPServer:
    """Forward a restricted MCP surface to the hosted service, never to a local engine."""

    def __init__(
        self,
        transport: RemoteTransport | None,
        *,
        provider_credential: ProviderCredential | None = None,
    ) -> None:
        self._transport = transport
        self._provider_credential = provider_credential

    @classmethod
    def from_config(
        cls,
        *,
        base_url: str,
        api_token: str,
        timeout_seconds: float,
        provider_credential: ProviderCredential | None = None,
    ) -> RemoteMCPServer:
        config = ClientConfig(
            api_url=base_url,
            api_key=api_token,
            timeout_seconds=timeout_seconds,
        )
        return cls(HTTPTransport(config), provider_credential=provider_credential)

    @classmethod
    def discovery_only(cls) -> RemoteMCPServer:
        """Serve introspection locally; every authenticated request fails closed."""
        return cls(None)

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()

    def handle_message(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        if message.get("jsonrpc") != "2.0":
            return _error(message, -32600, "Invalid Request")
        method = message.get("method")
        if not isinstance(method, str):
            return _error(message, -32600, "Invalid Request")
        if method in {"notifications/initialized", "notifications/cancelled", "$/cancelRequest"}:
            return None
        if method == "exit":
            return None
        if method == "shutdown":
            return {"jsonrpc": "2.0", "id": message.get("id"), "result": {}}
        if method not in _FORWARD_METHODS or message.get("id") is None:
            return _error(message, -32601, "Method not found")
        if method == "completion/complete":
            return _error(message, -32601, "Method not found")
        tool_name = self._tool_name(message) if method == "tools/call" else None
        if method == "tools/call" and tool_name not in _REMOTE_ACCEPTED_TOOLS:
            return _error(message, -32601, "Method not found")
        if tool_name == "adaptorch_run" and not self._valid_run_arguments(message):
            return _error(message, -32602, "Invalid tool arguments")
        if method == "resources/read":
            uri = _params(message).get("uri")
            if uri not in _REMOTE_RESOURCES:
                return _error(message, -32601, "Method not found")
        if self._transport is None:
            return self._discover(message)
        try:
            response = self._forward(message, tool_name=tool_name)
        except (AdaptOrchAPIError, ParentContractError, TypeError, ValueError):
            return _error(message, -32000, "Remote MCP request failed")
        return self._project(message, response, tool_name=tool_name)

    @staticmethod
    def _discover(message: Mapping[str, Any]) -> dict[str, Any]:
        method = message["method"]
        result: dict[str, Any]
        if method == "initialize":
            requested = _params(message).get("protocolVersion")
            result = {
                "protocolVersion": (
                    requested if requested in _SUPPORTED_PROTOCOLS else _SUPPORTED_PROTOCOLS[0]
                ),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "adaptorch-mcp", "version": __version__},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": discovery_catalog()}
        elif method in _DISCOVERY_EMPTY_LISTS:
            result = {_DISCOVERY_EMPTY_LISTS[method]: []}
        elif method in {"tools/call", "resources/read"}:
            return _error(message, -32001, _MISSING_TOKEN)
        else:
            return _error(message, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}

    def _forward(
        self,
        message: Mapping[str, Any],
        *,
        tool_name: str | None,
    ) -> dict[str, Any]:
        if self._transport is None:
            raise ParentContractError("discovery mode has no remote transport")
        credential = self._provider_credential if tool_name == "adaptorch_run" else None
        response = self._transport.request(
            RequestSpec(
                "POST",
                "/v1/mcp",
                payload=cast(Any, dict(message)),
                provider_credential=credential,
            )
        )
        if response.get("jsonrpc") != "2.0" or response.get("id") != message.get("id"):
            raise ParentContractError("remote MCP response identity differs")
        return dict(response)

    def _project(
        self,
        message: Mapping[str, Any],
        response: dict[str, Any],
        *,
        tool_name: str | None,
    ) -> dict[str, Any]:
        method = message["method"]
        if method == "tools/call" and tool_name is not None:
            run_id = _arguments(message).get("run_id", _arguments(message).get("resume_run_id"))
            if tool_name in CANDIDATE_TOOL_NAMES:
                report_id = _arguments(message).get("verification_id")
                return sanitize_tool_response(
                    response, tool_name=tool_name,
                    expected_verification_id=report_id if isinstance(report_id, str) else None,
                )
            return sanitize_tool_response(
                response,
                tool_name=tool_name,
                expected_run_id=run_id.strip() if isinstance(run_id, str) else None,
            )
        if method == "resources/read":
            return sanitize_resource_response(response, uri=str(_params(message)["uri"]))
        result = response.get("result")
        if not isinstance(result, dict):
            return response
        if method == "tools/list":
            tools = result.get("tools", [])
            if not isinstance(tools, list):
                raise ParentContractError("remote MCP tools are invalid")
            result["tools"] = [
                project_remote_tool(item)
                for item in tools
                if isinstance(item, Mapping) and item.get("name") in _REMOTE_ACCEPTED_TOOLS
            ]
        elif method == "resources/list":
            resources = result.get("resources", [])
            result["resources"] = (
                [
                    item
                    for item in resources
                    if isinstance(item, Mapping) and item.get("uri") in _REMOTE_RESOURCES
                ]
                if isinstance(resources, list)
                else []
            )
        elif method == "resources/templates/list":
            result["resourceTemplates"] = []
        elif method == "initialize":
            result["serverInfo"] = {"name": "adaptorch-mcp", "version": __version__}
            capabilities = result.get("capabilities")
            if isinstance(capabilities, dict):
                capabilities.pop("completions", None)
        return response

    @staticmethod
    def _tool_name(message: Mapping[str, Any]) -> str | None:
        name = _params(message).get("name")
        return name if isinstance(name, str) else None

    @staticmethod
    def _valid_run_arguments(message: Mapping[str, Any]) -> bool:
        arguments = _arguments(message)
        if {"trace", "verification_commands"} & set(arguments):
            return False
        for name in ("timeout_seconds", "poll_interval_seconds"):
            value = arguments.get(name)
            if value is not None and (
                type(value) not in (int, float) or not 0 < value <= TIMEOUT_MAX
            ):
                return False
        payload = arguments.get("payload")
        metadata = payload.get("metadata") if isinstance(payload, Mapping) else None
        mcp_metadata = metadata.get("mcp") if isinstance(metadata, Mapping) else None
        return not isinstance(mcp_metadata, Mapping) or "verification_commands" not in mcp_metadata
