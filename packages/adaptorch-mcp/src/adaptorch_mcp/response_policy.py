from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from adaptorch_mcp.output_schema import (
    project_catalog,
    project_server_info,
    project_tool_output,
)

_UNSUPPORTED_RESPONSE_TEXT: Final = json.dumps(
    {"error": "unsupported tool response format"},
    ensure_ascii=True,
)
# The engine's envelope for a control-plane HTTP refusal (adaptorch.mcp_server).
_CONTROL_PLANE_REJECTED: Final = "CONTROL_PLANE_REJECTED"
# Refusals the caller can fix themselves. By the control plane's contract their
# detail string is a stable code followed by the instruction a human needs (for
# 401 byok_credentials_required: the three X-Provider header names), so it is
# forwarded verbatim. Every other status keeps the code and drops operator text.
_CALLER_FIXABLE_STATUSES: Final = frozenset({401, 403})
_RESOURCE_PROJECTORS: Final = {
    "adaptorch://server-info": project_server_info,
    "adaptorch://plans/cloud": project_catalog,
}


def _error_envelope(response: Mapping[str, Any], code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": response.get("id"),
        "error": {"code": code, "message": message},
    }


def _unsupported_result(response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": response.get("id"),
        "result": {
            "content": [{"type": "text", "text": _UNSUPPORTED_RESPONSE_TEXT}],
            "isError": True,
        },
    }


def _decoded_text_content(result: Any) -> Mapping[str, Any] | None:
    content = result.get("content") if isinstance(result, Mapping) else None
    if not isinstance(content, list) or len(content) != 1:
        return None
    item = content[0]
    if not isinstance(item, Mapping) or item.get("type") != "text":
        return None
    text = item.get("text")
    if not isinstance(text, str):
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, Mapping) else None


def _projected_control_plane_rejection(decoded: Mapping[str, Any]) -> dict[str, Any] | None:
    """Bounded projection of a control-plane refusal; ``None`` unless well-formed."""
    if decoded.get("error") != _CONTROL_PLANE_REJECTED:
        return None
    status_code = decoded.get("status_code")
    message = decoded.get("message")
    if isinstance(status_code, bool) or not isinstance(status_code, int):
        return None
    if not isinstance(message, str):
        return None
    projected: dict[str, Any] = {"error": _CONTROL_PLANE_REJECTED, "status_code": status_code}
    if status_code in _CALLER_FIXABLE_STATUSES:
        projected["message"] = message
    return projected


def sanitize_tool_response(response: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    """Project a parent tool response onto its remote-safe public contract."""
    error = response.get("error")
    if isinstance(error, Mapping):
        code = error.get("code")
        if code == -32601:
            return _error_envelope(response, -32601, "Method not found")
        if code == -32602:
            return _error_envelope(response, -32602, "Invalid tool arguments")
        return _error_envelope(response, -32603, "Tool execution failed")

    result = response.get("result")
    # Only a real boolean counts: the parent's output is untrusted, so a
    # string "true" or a 1 must not be read as an error flag (or as its absence).
    error_flag = result.get("isError") if isinstance(result, Mapping) else None
    is_error = isinstance(error_flag, bool) and error_flag
    decoded = _decoded_text_content(result)
    projected: Mapping[str, Any] | None = None
    if decoded is not None and is_error:
        projected = _projected_control_plane_rejection(decoded)
    if projected is None and decoded is not None:
        projected = project_tool_output(tool_name, decoded)
    if projected is None:
        return _unsupported_result(response)
    sanitized_result: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(projected, ensure_ascii=True, indent=2),
            }
        ],
        "isError": is_error,
    }
    if tool_name == "adaptorch_get_run":
        sanitized_result["structuredContent"] = projected
    return {
        "jsonrpc": "2.0",
        "id": response.get("id"),
        "result": sanitized_result,
    }


def sanitize_resource_response(response: dict[str, Any], *, uri: str) -> dict[str, Any]:
    """Project an allowed remote resource onto its facade capabilities."""
    result = response.get("result")
    contents = result.get("contents") if isinstance(result, Mapping) else None
    if not isinstance(contents, list) or len(contents) != 1:
        return _error_envelope(response, -32603, "Resource projection failed")
    item = contents[0]
    if not isinstance(item, Mapping) or item.get("uri") != uri:
        return _error_envelope(response, -32603, "Resource projection failed")
    text = item.get("text")
    if not isinstance(text, str):
        return _error_envelope(response, -32603, "Resource projection failed")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return _error_envelope(response, -32603, "Resource projection failed")
    if not isinstance(decoded, Mapping):
        return _error_envelope(response, -32603, "Resource projection failed")

    projector = _RESOURCE_PROJECTORS.get(uri)
    projected = projector(decoded) if projector is not None else None
    if projected is None:
        return _error_envelope(response, -32603, "Resource projection failed")
    return {
        "jsonrpc": "2.0",
        "id": response.get("id"),
        "result": {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(projected, ensure_ascii=True, indent=2),
                }
            ]
        },
    }
