from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

MAX_CONTEXT_ITEMS: Final = 16
MAX_CONTEXT_LENGTH: Final = 256
RUN_SCALAR_KEYS: Final = frozenset(
    {
        "run_id",
        "status",
        "result_status",
        "evaluation_status",
        "score_validity_status",
        "topology",
        "consistency",
        "error_class",
        "model",
        "synthesis_mode",
        "cse_state",
        "created_at",
        "started_at",
        "finished_at",
        "duration_ms",
    }
)
_VERDICTS: Final = frozenset({"PASS", "ADVISORY", "INCONCLUSIVE", "BLOCKED"})
_RECOMMENDED_ACTIONS: Final = frozenset({"observe", "deep_check", "human_review"})
_CONTEXT_FIELDS: Final = ("blockers", "advisories", "evidence_notes")
_CLAIM_BOUNDARY_FIELDS: Final = {
    "is_correctness_proof": False,
    "is_active_selector": False,
    "is_shadow_observability_only": True,
    "real_docker_paired_required_for_promotion": True,
}


def _project_context(value: Any) -> list[str] | None:
    if not isinstance(value, list) or len(value) > MAX_CONTEXT_ITEMS:
        return None
    if not all(
        isinstance(item, str) and 0 < len(item) <= MAX_CONTEXT_LENGTH for item in value
    ):
        return None
    return list(value)


def _project_claim_boundary(value: Any) -> dict[str, bool] | None:
    if not isinstance(value, Mapping) or not all(
        value.get(key) is expected for key, expected in _CLAIM_BOUNDARY_FIELDS.items()
    ):
        return None
    return dict(_CLAIM_BOUNDARY_FIELDS)


def project_correctness_wall(value: Any) -> dict[str, Any] | None:
    """Project a bounded, non-authorizing Correctness Wall API view."""
    if not isinstance(value, Mapping):
        return None
    verdict = value.get("verdict")
    recommended_action = value.get("recommended_action")
    selection_mutated = value.get("selection_mutated")
    if (
        not isinstance(verdict, str)
        or verdict not in _VERDICTS
        or not isinstance(recommended_action, str)
        or recommended_action not in _RECOMMENDED_ACTIONS
        or value.get("correctness_claim") is not False
        or not isinstance(selection_mutated, bool)
    ):
        return None
    contexts = {field: _project_context(value.get(field)) for field in _CONTEXT_FIELDS}
    boundary = _project_claim_boundary(value.get("claim_boundary"))
    if boundary is None or any(item is None for item in contexts.values()):
        return None
    return {
        "verdict": verdict,
        "blockers": contexts["blockers"],
        "advisories": contexts["advisories"],
        "evidence_notes": contexts["evidence_notes"],
        "correctness_claim": False,
        "selection_mutated": selection_mutated,
        "recommended_action": recommended_action,
        "claim_boundary": boundary,
    }


def _context_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": MAX_CONTEXT_ITEMS,
        "items": {"type": "string", "minLength": 1, "maxLength": MAX_CONTEXT_LENGTH},
    }


def correctness_wall_output_schema() -> dict[str, Any]:
    """Return a fresh closed JSON Schema for the bounded wall projection."""
    return {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
            "verdict": {"type": "string", "enum": sorted(_VERDICTS)},
            "blockers": _context_schema(),
            "advisories": _context_schema(),
            "evidence_notes": _context_schema(),
            "correctness_claim": {"const": False},
            "selection_mutated": {"type": "boolean"},
            "recommended_action": {
                "type": "string",
                "enum": sorted(_RECOMMENDED_ACTIONS),
            },
            "claim_boundary": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    key: {"const": expected}
                    for key, expected in _CLAIM_BOUNDARY_FIELDS.items()
                },
                "required": list(_CLAIM_BOUNDARY_FIELDS),
            },
        },
        "required": [
            "verdict",
            "blockers",
            "advisories",
            "evidence_notes",
            "correctness_claim",
            "selection_mutated",
            "recommended_action",
            "claim_boundary",
        ],
    }


def get_run_output_schema() -> dict[str, Any]:
    """Return the closed structured-output schema for remote get-run results."""
    scalar_types = ["string", "number", "integer", "boolean", "null"]
    properties: dict[str, Any] = {
        key: {"type": scalar_types} for key in RUN_SCALAR_KEYS
    }
    properties["run_id"] = {"type": "string"}
    properties["status"] = {"type": "string"}
    properties["artifact_urls"] = {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    properties["correctness_wall"] = correctness_wall_output_schema()
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": ["run_id", "status"],
    }
