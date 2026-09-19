from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from adaptorch_mcp.discovery_output import project_catalog, project_server_info
from adaptorch_mcp.output_schema import project_tool_output
from adaptorch_mcp.response_json import decode_response_text

_UNSUPPORTED_RESPONSE_TEXT: Final = json.dumps(
    {"error": "unsupported tool response format"},
    ensure_ascii=True,
)
# The engine's envelope for a control-plane HTTP refusal (adaptorch.mcp_server).
_CONTROL_PLANE_REJECTED: Final = "CONTROL_PLANE_REJECTED"
# The engine's envelope for a non-4xx control-plane status: the deployment is
# unavailable (a Railway redeploy returns 502/503). It carries the status and a
# retry hint so an agent can decide to retry instead of giving up blind.
_CONTROL_PLANE_UNAVAILABLE: Final = "CONTROL_PLANE_UNAVAILABLE"
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
    return decode_response_text(text)


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


def _projected_control_plane_unavailable(decoded: Mapping[str, Any]) -> dict[str, Any] | None:
    """Bounded projection of an availability failure; ``None`` unless well-formed.

    Without this the remote profile replaced the whole envelope with
    "unsupported tool response format", which is strictly less useful than the
    opaque engine message it replaced.
    """
    if decoded.get("error") != _CONTROL_PLANE_UNAVAILABLE:
        return None
    status_code = decoded.get("status_code")
    retryable = decoded.get("retryable")
    message = decoded.get("message")
    if isinstance(status_code, bool) or not isinstance(status_code, int):
        return None
    if not isinstance(retryable, bool):
        return None
    if not isinstance(message, str) or not message:
        return None
    return {
        "error": _CONTROL_PLANE_UNAVAILABLE,
        "status_code": status_code,
        "retryable": retryable,
        "message": message,
    }


def _projected_quota_rejection(decoded: Mapping[str, Any]) -> dict[str, Any] | None:
    usage = decoded.get("usage")
    if decoded.get("error") != "QUOTA_EXCEEDED" or not isinstance(usage, Mapping):
        return None
    safe: dict[str, Any] = {}
    for key in ("limit", "used", "remaining"):
        if key in usage:
            item = usage[key]
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                return None
            safe[key] = item
    for key in ("plan_level", "period", "upgrade_url"):
        if key in usage:
            item = usage[key]
            if not isinstance(item, str) or not 0 < len(item) <= 2048 or not item.isprintable():
                return None
            if key == "upgrade_url" and (
                not item.startswith("/") or item.startswith("//") or "\\" in item
            ):
                return None
            safe[key] = item
    if "grace_exhausted" in usage:
        if not isinstance(usage["grace_exhausted"], bool):
            return None
        safe["grace_exhausted"] = usage["grace_exhausted"]
    return {
        "error": "QUOTA_EXCEEDED",
        "message": "Tenant quota exhausted for the current period",
        "usage": safe,
    }


def sanitize_tool_response(
    response: dict[str, Any],
    *,
    tool_name: str,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
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
    if isinstance(result, Mapping) and "isError" in result and not isinstance(error_flag, bool):
        return _unsupported_result(response)
    is_error = isinstance(error_flag, bool) and error_flag
    decoded = _decoded_text_content(result)
    projected: Mapping[str, Any] | None = None
    if decoded is not None and is_error:
        projected = _projected_control_plane_rejection(decoded)
        if projected is None:
            projected = _projected_control_plane_unavailable(decoded)
        if projected is None:
            projected = _projected_quota_rejection(decoded)
    if projected is None and decoded is not None:
        projected = project_tool_output(tool_name, decoded)
        if projected is not None and expected_run_id is not None:
            if projected.get("run_id") != expected_run_id:
                return _unsupported_result(response)
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
    if tool_name == "adaptorch_get_run" and not is_error:
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
    decoded = decode_response_text(text)
    if decoded is None:
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
