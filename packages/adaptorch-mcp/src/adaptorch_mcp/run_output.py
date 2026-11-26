"""One closed scalar contract shared by run projection and its advertised schema."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Final, TypeAlias, TypeGuard

JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
_STRING_KEYS: Final = frozenset(
    {
        "run_id",
        "status",
        "result_status",
        "evaluation_status",
        "score_validity_status",
        "topology",
        "error_class",
        "model",
        "model_selection_source",
        "synthesis_mode",
        "synthesis_mode_requested",
        "synthesis_mode_used",
        "auto_synthesis_reason",
        "cse_state",
        "created_at",
        "started_at",
        "finished_at",
        # Stability surface (2026-09-20): the engine's own metadata, never
        # execution claims. `request_idempotency_key` echoes the caller's key.
        "request_idempotency_key",
        "collection_status",
        "artifact_status",
    }
)
RUN_SCALAR_KEYS: Final = _STRING_KEYS | {"consistency", "duration_ms"}


def project_run_scalars(value: Mapping[str, JSONValue]) -> dict[str, JSONValue] | None:
    """Preserve server observations without inferring execution or correctness from status."""
    for key in ("run_id", "status"):
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            return None
    projected: dict[str, JSONValue] = {}
    for key in _STRING_KEYS:
        if key in value:
            item = value[key]
            if item is not None and not isinstance(item, str):
                return None
            projected[key] = item
    if "consistency" in value:
        item = value["consistency"]
        if item is not None and (
            isinstance(item, bool)
            or not isinstance(item, int | float)
            or not 0 <= item <= 1
            or not math.isfinite(item)
        ):
            return None
        projected["consistency"] = item
    if "duration_ms" in value:
        item = value["duration_ms"]
        if item is not None and (isinstance(item, bool) or not isinstance(item, int) or item < 0):
            return None
        projected["duration_ms"] = item
    return projected


RUN_OUTPUT_SCHEMA_VERSION: Final = "run-output.v1"
RUN_GENERATION_SCHEMA_VERSION: Final = "run-generation.v1"
RUN_GENERATION_SCOPE: Final = "observed_usage_events"
RUN_GENERATION_STATES: Final[tuple[str, ...]] = (
    "limit_observed",
    "stop_observed",
    "unknown",
)
_MAX_OUTPUT_SUBTASKS: Final = 256
_MAX_THOUGHT_SEGMENTS: Final = 256


def _non_neg_int(value: object) -> TypeGuard[int]:
    return type(value) is int and value >= 0


def _project_generation(value: object) -> dict[str, JSONValue] | None:
    if not isinstance(value, Mapping):
        return None
    if (
        value.get("schema_version") != RUN_GENERATION_SCHEMA_VERSION
        or value.get("scope") != RUN_GENERATION_SCOPE
    ):
        return None
    state = value.get("state")
    if not isinstance(state, str) or state not in RUN_GENERATION_STATES:
        return None
    counts: dict[str, int] = {}
    for key in ("settlement_events", "limit_events", "stop_events", "unknown_events"):
        raw = value.get(key)
        if not _non_neg_int(raw):
            return None
        counts[key] = int(raw)
    if counts["settlement_events"] != (
        counts["limit_events"] + counts["stop_events"] + counts["unknown_events"]
    ):
        return None
    return {
        "schema_version": RUN_GENERATION_SCHEMA_VERSION,
        "scope": RUN_GENERATION_SCOPE,
        "state": state,
        **counts,
    }


def _project_answer(value: object) -> dict[str, JSONValue] | None:
    if not isinstance(value, Mapping):
        return None
    state, source = value.get("state"), value.get("source")
    text = value.get("text")
    if (
        not isinstance(state, str)
        or not state
        or not isinstance(source, str)
        or not source
        or (text is not None and not isinstance(text, str))
    ):
        return None
    projected: dict[str, JSONValue] = {"state": state, "text": text, "source": source}
    if "bytes" in value:
        raw_bytes = value["bytes"]
        if not _non_neg_int(raw_bytes):
            return None
        projected["bytes"] = int(raw_bytes)
    if "sha256" in value:
        sha = value["sha256"]
        if not isinstance(sha, str) or not sha:
            return None
        projected["sha256"] = sha
    return projected


def _project_subtask_outputs(value: object) -> list[JSONValue] | None:
    if not isinstance(value, list) or len(value) > _MAX_OUTPUT_SUBTASKS:
        return None
    rows: list[JSONValue] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        subtask_id, text = item.get("id"), item.get("text")
        size, truncated = item.get("bytes"), item.get("truncated")
        if (
            not isinstance(subtask_id, str)
            or not subtask_id
            or not isinstance(text, str)
            or not _non_neg_int(size)
            or type(truncated) is not bool
        ):
            return None
        row: dict[str, JSONValue] = {
            "id": subtask_id,
            "text": text,
            "bytes": int(size),
            "truncated": truncated,
        }
        if "display_truncated" in item:
            display_truncated = item["display_truncated"]
            if type(display_truncated) is not bool:
                return None
            row["display_truncated"] = display_truncated
        if "returned_bytes" in item:
            returned_bytes = item["returned_bytes"]
            if not _non_neg_int(returned_bytes):
                return None
            row["returned_bytes"] = int(returned_bytes)
        rows.append(row)
    return rows


def _project_thought(value: object) -> dict[str, JSONValue] | None:
    if not isinstance(value, Mapping):
        return None
    state = value.get("state")
    visibility = value.get("visibility")
    is_evidence = value.get("is_evidence")
    dropped = value.get("dropped_segments")
    notice = value.get("notice")
    raw_segments = value.get("segments")
    if (
        not isinstance(state, str)
        or not state
        or visibility != "model_reported"
        or is_evidence is not False
        or not _non_neg_int(dropped)
        or not isinstance(notice, str)
        or not isinstance(raw_segments, list)
        or len(raw_segments) > _MAX_THOUGHT_SEGMENTS
    ):
        return None
    segments: list[JSONValue] = []
    for seg in raw_segments:
        if not isinstance(seg, Mapping):
            return None
        subtask_id = seg.get("subtask_id")
        if subtask_id is not None and not isinstance(subtask_id, str):
            return None
        role = seg.get("role")
        provider = seg.get("provider")
        model = seg.get("model")
        source_field = seg.get("source_field")
        text = seg.get("text")
        size = seg.get("bytes")
        truncated = seg.get("truncated")
        redactions = seg.get("redactions")
        reasoning_tokens = seg.get("reasoning_tokens")
        if (
            not isinstance(role, str)
            or not isinstance(provider, str)
            or not isinstance(model, str)
            or not isinstance(source_field, str)
            or not isinstance(text, str)
            or not _non_neg_int(size)
            or type(truncated) is not bool
            or not _non_neg_int(redactions)
            or (reasoning_tokens is not None and not _non_neg_int(reasoning_tokens))
        ):
            return None
        segments.append(
            {
                "subtask_id": subtask_id,
                "role": role,
                "provider": provider,
                "model": model,
                "source_field": source_field,
                "text": text,
                "bytes": int(size),
                "truncated": truncated,
                "redactions": int(redactions),
                "reasoning_tokens": (
                    int(reasoning_tokens)
                    if reasoning_tokens is not None
                    else None
                ),
            }
        )
    return {
        "state": state,
        "visibility": "model_reported",
        "is_evidence": False,
        "segments": segments,
        "dropped_segments": int(dropped),
        "notice": notice,
    }


def project_run_output(value: object) -> dict[str, JSONValue] | None:
    """Project optional ``run-output.v1`` + ``run-generation.v1`` payload."""
    if not isinstance(value, Mapping):
        return None
    if value.get("schema_version") != RUN_OUTPUT_SCHEMA_VERSION:
        return None
    run_id = value.get("run_id")
    status = value.get("status")
    model = value.get("model")
    ai_generated = value.get("ai_generated")
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or not isinstance(status, str)
        or not status.strip()
        or (model is not None and not isinstance(model, str))
        or ai_generated is not True
    ):
        return None
    answer = _project_answer(value.get("answer"))
    subtasks = _project_subtask_outputs(value.get("subtasks"))
    thought = _project_thought(value.get("thought"))
    if answer is None or subtasks is None or thought is None:
        return None
    projected: dict[str, JSONValue] = {
        "schema_version": RUN_OUTPUT_SCHEMA_VERSION,
        "run_id": run_id,
        "status": status,
        "model": model,
        "answer": answer,
        "subtasks": subtasks,
        "thought": thought,
        "ai_generated": True,
    }
    if "generation" in value:
        generation = _project_generation(value["generation"])
        if generation is None:
            return None
        projected["generation"] = generation
    return projected


def run_output_payload_schema() -> dict[str, JSONValue]:
    """Closed JSON Schema for optional ``adaptorch_get_run(..., include_output=True)``."""
    return {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "const": RUN_OUTPUT_SCHEMA_VERSION},
            "run_id": {"type": "string", "minLength": 1},
            "status": {"type": "string", "minLength": 1},
            "model": {"type": ["string", "null"]},
            "ai_generated": {"const": True},
            "answer": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "state": {"type": "string", "minLength": 1},
                    "text": {"type": ["string", "null"]},
                    "source": {"type": "string", "minLength": 1},
                    "bytes": {"type": "integer", "minimum": 0},
                    "sha256": {"type": "string", "minLength": 1},
                },
                "required": ["state", "text", "source"],
            },
            "subtasks": {
                "type": "array",
                "maxItems": _MAX_OUTPUT_SUBTASKS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "text": {"type": "string"},
                        "bytes": {"type": "integer", "minimum": 0},
                        "truncated": {"type": "boolean"},
                        "display_truncated": {"type": "boolean"},
                        "returned_bytes": {"type": "integer", "minimum": 0},
                    },
                    "required": ["id", "text", "bytes", "truncated"],
                },
            },
            "generation": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "schema_version": {"type": "string", "const": RUN_GENERATION_SCHEMA_VERSION},
                    "scope": {"type": "string", "const": RUN_GENERATION_SCOPE},
                    "state": {"type": "string", "enum": list(RUN_GENERATION_STATES)},
                    "settlement_events": {"type": "integer", "minimum": 0},
                    "limit_events": {"type": "integer", "minimum": 0},
                    "stop_events": {"type": "integer", "minimum": 0},
                    "unknown_events": {"type": "integer", "minimum": 0},
                },
                "required": [
                    "schema_version",
                    "scope",
                    "state",
                    "settlement_events",
                    "limit_events",
                    "stop_events",
                    "unknown_events",
                ],
            },
            "thought": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "state": {"type": "string", "minLength": 1},
                    "visibility": {"type": "string", "const": "model_reported"},
                    "is_evidence": {"const": False},
                    "dropped_segments": {"type": "integer", "minimum": 0},
                    "notice": {"type": "string"},
                    "segments": {
                        "type": "array",
                        "maxItems": _MAX_THOUGHT_SEGMENTS,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "subtask_id": {"type": ["string", "null"]},
                                "role": {"type": "string"},
                                "provider": {"type": "string"},
                                "model": {"type": "string"},
                                "source_field": {"type": "string"},
                                "text": {"type": "string"},
                                "bytes": {"type": "integer", "minimum": 0},
                                "truncated": {"type": "boolean"},
                                "redactions": {"type": "integer", "minimum": 0},
                                "reasoning_tokens": {"type": ["integer", "null"], "minimum": 0},
                            },
                            "required": [
                                "subtask_id",
                                "role",
                                "provider",
                                "model",
                                "source_field",
                                "text",
                                "bytes",
                                "truncated",
                                "redactions",
                                "reasoning_tokens",
                            ],
                        },
                    },
                },
                "required": [
                    "state",
                    "visibility",
                    "is_evidence",
                    "segments",
                    "dropped_segments",
                    "notice",
                ],
            },
        },
        "required": [
            "schema_version",
            "run_id",
            "status",
            "model",
            "answer",
            "subtasks",
            "thought",
            "ai_generated",
        ],
    }


def run_scalar_schema() -> dict[str, JSONValue]:
    properties: dict[str, JSONValue] = {key: {"type": ["string", "null"]} for key in _STRING_KEYS}
    properties["run_id"] = {"type": "string", "minLength": 1}
    properties["status"] = {"type": "string", "minLength": 1}
    properties["consistency"] = {"type": ["number", "null"], "minimum": 0, "maximum": 1}
    properties["duration_ms"] = {"type": ["integer", "null"], "minimum": 0}
    properties["synthesis_mode_used"] = {
        "type": ["string", "null"],
        "description": (
            "Serving-layer selected mode as reported by the parent; "
            "not proof of final engine execution."
        ),
    }
    return properties
