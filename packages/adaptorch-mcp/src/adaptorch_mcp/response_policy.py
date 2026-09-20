from __future__ import annotations

import json
import math
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

# Vocabularies owned by adaptorch.connector_stability.connector_error_payload.
# The wrapper re-lists them once so an older engine's envelope still projects,
# and a value outside the set fails closed rather than being forwarded.
_RECOVERY_REASONS: Final = frozenset(
    {
        "http_transient",
        "rate_limited",
        "quota_exceeded",
        "authentication",
        "request_rejected",
        "redirect_blocked",
        "network",
        "tls",
        "dns",
        "protocol",
        "response_too_large",
        "deadline",
        "cancelled",
        "circuit_open",
        "busy",
    }
)
_RECOVERY_OUTCOMES: Final = frozenset({"unknown", "not_sent", "read_only", "response_received"})
_RECOVERY_ACTIONS: Final = frozenset(
    {
        "reuse_same_request_and_key",
        "retry_read",
        "retry_artifact_read",
        "resume_existing_run",
        "inspect_existing_runs_before_resubmitting",
    }
)


def _bounded_str(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str) or not 0 < len(value) <= maximum or not value.isprintable():
        return None
    return value


def _project_recovery_fields(
    decoded: Mapping[str, Any], projected: dict[str, Any]
) -> dict[str, Any] | None:
    """Carry the engine's allowlisted recovery metadata onto an error envelope.

    Every field is validated against the connector's own vocabulary — never
    ``str(exc)`` or an upstream body. Returns ``None`` (fail closed) on a
    malformed field rather than forwarding it.
    """
    reason = decoded.get("reason")
    if reason is not None:
        if reason not in _RECOVERY_REASONS:
            return None
        projected["reason"] = reason
    outcome = decoded.get("request_outcome")
    if outcome is not None:
        if outcome not in _RECOVERY_OUTCOMES:
            return None
        projected["request_outcome"] = outcome
    if "new_run_safe" in decoded:
        # Only False is publishable: the wrapper never lets a parent tell the
        # caller a fresh submission is safe after an uncertain request.
        new_run_safe = decoded["new_run_safe"]
        if not isinstance(new_run_safe, bool) or new_run_safe:
            return None
        projected["new_run_safe"] = False
    action = decoded.get("next_action")
    if action is not None:
        if action not in _RECOVERY_ACTIONS:
            return None
        projected["next_action"] = action
    for key in ("run_id", "idempotency_key"):
        item = decoded.get(key)
        if item is not None:
            bounded = _bounded_str(item, 256)
            if bounded is None:
                return None
            projected[key] = bounded
    attempts = decoded.get("attempts")
    if attempts is not None:
        if (
            isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or not 0 <= attempts <= 10000
        ):
            return None
        projected["attempts"] = attempts
    retry_after = decoded.get("retry_after_seconds")
    if retry_after is not None:
        if (
            isinstance(retry_after, bool)
            or not isinstance(retry_after, int | float)
            or not math.isfinite(retry_after)
            or retry_after < 0
        ):
            return None
        projected["retry_after_seconds"] = retry_after
    return projected


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
    message_ko = decoded.get("message_ko")
    if message_ko is not None:
        bounded_ko = _bounded_str(message_ko, 1024)
        if bounded_ko is None:
            return None
        projected["message_ko"] = bounded_ko
    return _project_recovery_fields(decoded, projected)


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
    # Transport-layer failures (DNS/TLS/network) carry no HTTP status; the
    # engine reports them as status_code=None rather than omitting the field.
    if status_code is not None and (
        isinstance(status_code, bool)
        or not isinstance(status_code, int)
        or not 100 <= status_code <= 599
    ):
        return None
    if not isinstance(retryable, bool):
        return None
    if not isinstance(message, str) or not message:
        return None
    projected: dict[str, Any] = {
        "error": _CONTROL_PLANE_UNAVAILABLE,
        "status_code": status_code,
        "retryable": retryable,
        "message": message,
    }
    message_ko = decoded.get("message_ko")
    if message_ko is not None:
        bounded_ko = _bounded_str(message_ko, 1024)
        if bounded_ko is None:
            return None
        projected["message_ko"] = bounded_ko
    return _project_recovery_fields(decoded, projected)


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
