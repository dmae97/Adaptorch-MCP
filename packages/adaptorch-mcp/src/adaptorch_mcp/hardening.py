from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from adaptorch.mcp_server import AdaptOrchMCPServer, MCPToolBackend, NotificationSink
from adaptorch.n8n_connector import N8nConnectorConfig, N8nControlPlaneConnector

from adaptorch_mcp.response_policy import sanitize_tool_response
from adaptorch_mcp.security_policy import (
    FULL_EXPOSURE_PROFILE,
    REMOTE_EXPOSURE_PROFILE,
    ExposureProfile,
    insecure_control_plane_allowed,
    resolve_exposure_profile,
    validate_control_plane_url,
    validate_http_binding,
    validate_separate_tokens,
)

__all__ = [
    "FULL_EXPOSURE_PROFILE",
    "REMOTE_EXPOSURE_PROFILE",
    "REMOTE_TOOL_NAMES",
    "ExposureProfile",
    "HardenedMCPServer",
    "build_hardened_mcp_server",
    "insecure_control_plane_allowed",
    "resolve_exposure_profile",
    "validate_control_plane_url",
    "validate_http_binding",
    "validate_parent_tools",
    "validate_separate_tokens",
]

REMOTE_TOOL_NAMES: Final = (
    "adaptorch_run",
    "adaptorch_get_run",
    "adaptorch_get_artifacts",
    "adaptorch_list_runs",
    "adaptorch_cancel_run",
    "adaptorch_server_metrics",
    "adaptorch_capabilities",
    "adaptorch_plan_catalog",
)
_REQUIRED_FULL_TOOL_NAMES: Final = (
    *REMOTE_TOOL_NAMES[:4],
    "adaptorch_get_traces",
    *REMOTE_TOOL_NAMES[4:5],
    "adaptorch_route_topology",
    *REMOTE_TOOL_NAMES[5:],
)
_REMOTE_RESOURCE_URIS: Final = frozenset(
    {"adaptorch://server-info", "adaptorch://plans/cloud"}
)


def validate_parent_tools(
    tool_names: tuple[str, ...],
    exposure_profile: ExposureProfile,
) -> None:
    """Fail closed when the installed parent lacks the required MCP contract."""
    required = (
        REMOTE_TOOL_NAMES
        if exposure_profile == REMOTE_EXPOSURE_PROFILE
        else _REQUIRED_FULL_TOOL_NAMES
    )
    missing = [name for name in required if name not in tool_names]
    if missing:
        raise RuntimeError("parent AdaptOrch MCP is missing required tools: " + ", ".join(missing))


def _jsonrpc_error(message: Mapping[str, Any], code: int, text: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message.get("id"),
        "error": {"code": code, "message": text},
    }


def _tool_name(message: Mapping[str, Any]) -> str | None:
    params = message.get("params")
    if not isinstance(params, Mapping):
        return None
    name = params.get("name")
    return name if isinstance(name, str) else None


def _run_arguments(message: Mapping[str, Any]) -> Mapping[str, Any]:
    params = message.get("params")
    if not isinstance(params, Mapping):
        return {}
    arguments = params.get("arguments")
    return arguments if isinstance(arguments, Mapping) else {}


def _run_requests_trace(message: Mapping[str, Any]) -> bool:
    return _run_arguments(message).get("trace") is True


def _run_requests_verification_commands(message: Mapping[str, Any]) -> bool:
    arguments = _run_arguments(message)
    if "verification_commands" in arguments:
        return True
    payload = arguments.get("payload")
    if not isinstance(payload, Mapping):
        return False
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    mcp_metadata = metadata.get("mcp")
    return isinstance(mcp_metadata, Mapping) and "verification_commands" in mcp_metadata


class HardenedMCPServer(AdaptOrchMCPServer):
    """Canonical parent MCP server with a fail-closed public exposure policy."""

    def __init__(
        self,
        *,
        backend: MCPToolBackend,
        exposure_profile: ExposureProfile,
    ) -> None:
        if exposure_profile not in {REMOTE_EXPOSURE_PROFILE, FULL_EXPOSURE_PROFILE}:
            raise ValueError("exposure profile must be 'remote' or 'full'")
        super().__init__(backend=backend)
        self._exposure_profile = exposure_profile
        parent_response = super().handle_message(
            {"jsonrpc": "2.0", "id": 0, "method": "tools/list", "params": {}}
        )
        if parent_response is None:
            raise RuntimeError("parent AdaptOrch MCP did not return its tool contract")
        tools = parent_response.get("result", {}).get("tools", [])
        names = tuple(
            item["name"]
            for item in tools
            if isinstance(item, Mapping) and isinstance(item.get("name"), str)
        )
        validate_parent_tools(names, exposure_profile)

    @property
    def exposure_profile(self) -> ExposureProfile:
        return self._exposure_profile

    def set_notification_sink(self, sink: NotificationSink | None) -> None:
        super().set_notification_sink(
            sink if self._exposure_profile == FULL_EXPOSURE_PROFILE else None
        )

    def handle_message(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        if self._exposure_profile == FULL_EXPOSURE_PROFILE:
            return super().handle_message(message)

        method = message.get("method")
        if method == "tools/call":
            name = _tool_name(message)
            if name not in REMOTE_TOOL_NAMES:
                return _jsonrpc_error(message, -32601, "Method not found")
            if name == "adaptorch_run" and _run_requests_trace(message):
                return _jsonrpc_error(message, -32602, "trace is unavailable in remote profile")
            if name == "adaptorch_run" and _run_requests_verification_commands(message):
                return _jsonrpc_error(
                    message,
                    -32602,
                    "verification_commands is unavailable in remote profile",
                )
        if method == "resources/read":
            params = message.get("params")
            uri = params.get("uri") if isinstance(params, Mapping) else None
            if uri not in _REMOTE_RESOURCE_URIS:
                return _jsonrpc_error(message, -32601, "Method not found")
        if method == "completion/complete":
            return _jsonrpc_error(message, -32601, "Method not found")

        response = super().handle_message(message)
        if response is None:
            return None
        if method == "tools/call":
            return sanitize_tool_response(response)
        result = response.get("result")
        if not isinstance(result, dict):
            return response
        if method == "tools/list":
            tools = result.get("tools", [])
            result["tools"] = [
                item
                for item in tools
                if isinstance(item, Mapping) and item.get("name") in REMOTE_TOOL_NAMES
            ]
        elif method == "resources/list":
            resources = result.get("resources", [])
            result["resources"] = [
                item
                for item in resources
                if isinstance(item, Mapping) and item.get("uri") in _REMOTE_RESOURCE_URIS
            ]
        elif method == "resources/templates/list":
            result["resourceTemplates"] = []
        elif method == "initialize":
            capabilities = result.get("capabilities")
            if isinstance(capabilities, dict):
                capabilities.pop("completions", None)
        return response


def build_hardened_mcp_server(
    *,
    base_url: str,
    api_token: str,
    timeout_seconds: float,
    exposure_profile: ExposureProfile,
    allow_insecure: bool,
) -> HardenedMCPServer:
    """Build the parent control-plane backend behind the hardened MCP facade."""
    validated_url = validate_control_plane_url(base_url, allow_insecure=allow_insecure)
    backend = N8nControlPlaneConnector(
        N8nConnectorConfig(
            base_url=validated_url,
            api_token=api_token.strip(),
            timeout_seconds=timeout_seconds,
        )
    )
    return HardenedMCPServer(backend=backend, exposure_profile=exposure_profile)
