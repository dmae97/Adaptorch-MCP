"""One closed scalar contract shared by run projection and its advertised schema."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Final, TypeAlias

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
