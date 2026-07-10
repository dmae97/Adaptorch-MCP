from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

_REDACTED_RESULT_KEYS: Final = frozenset(
    {
        "diagnostics",
        "telemetry",
        "topology_evidence",
        "routing_features",
        "routing_scores",
        "candidate_scores",
        "thresholds",
        "decision_trace",
        "traces",
    }
)


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_json(item)
            for key, item in value.items()
            if str(key) not in _REDACTED_RESULT_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    return value


def sanitize_tool_response(response: dict[str, Any]) -> dict[str, Any]:
    """Remove algorithm-sensitive diagnostics from JSON text tool results."""
    result = response.get("result")
    if not isinstance(result, Mapping):
        return response
    content = result.get("content")
    if not isinstance(content, list):
        return response

    sanitized_content: list[Any] = []
    for item in content:
        if not isinstance(item, Mapping) or not isinstance(item.get("text"), str):
            sanitized_content.append(item)
            continue
        copied = dict(item)
        try:
            decoded = json.loads(copied["text"])
        except json.JSONDecodeError:
            sanitized_content.append(copied)
            continue
        copied["text"] = json.dumps(_sanitize_json(decoded), ensure_ascii=True, indent=2)
        sanitized_content.append(copied)

    copied_result = dict(result)
    copied_result["content"] = sanitized_content
    copied_response = dict(response)
    copied_response["result"] = copied_result
    return copied_response
