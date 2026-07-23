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
    decoded = _decoded_text_content(result)
    projected = project_tool_output(tool_name, decoded) if decoded is not None else None
    if projected is None:
        return _unsupported_result(response)
    sanitized_result: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(projected, ensure_ascii=True, indent=2),
            }
        ],
        "isError": isinstance(result, Mapping) and result.get("isError") is True,
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
