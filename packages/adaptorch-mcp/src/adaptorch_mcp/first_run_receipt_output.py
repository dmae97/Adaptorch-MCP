"""Bounded projection of the engine's B2C first-run receipt.

`correctness_wall` answers an auditor's question. This answers a paying
consumer's: did my run work, did it stay inside my budget, was it verified.

The receipt is built from the user's own prompt and is persisted next to a
server artifact path and a keyed digest, so the wrapper republishes only the
verdict vocabulary and never trusts the parent to have stripped the rest. A
receipt that claims more than the beta supports is dropped, not forwarded.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

MAX_POSITIONING_LENGTH: Final = 64

# Kept literal so the wrapper still validates receipts from engines that predate
# the exported vocabulary. test_engine_algorithm_parity asserts equality with
# adaptorch.b2c_first_run whenever the installed engine exports them.
RECEIPT_VERDICTS: Final[tuple[str, ...]] = ("OK", "DEGRADED", "FAILED")
BUDGET_STATES: Final[tuple[str, ...]] = (
    "within_cap",
    "cap_missing",
    "cap_untrusted",
    "cost_unknown",
    "cap_exceeded",
)
VERIFICATION_STATES: Final[tuple[str, ...]] = ("passed", "failed", "not_run", "error")
CLAIM_STATES: Final[tuple[str, ...]] = ("beta_only",)
CLAIM_BOUNDARY_FIELDS: Final[dict[str, bool]] = {
    "b2c_launch_ready": False,
    "full50_claimed": False,
    "official_correctness_claimed": False,
}
"""Claims whose only publishable value is False while the product is beta."""


def _claims(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or any(
        value.get(field) is not expected for field, expected in CLAIM_BOUNDARY_FIELDS.items()
    ):
        return None
    state = value.get("state")
    positioning = value.get("positioning")
    if (
        not isinstance(state, str)
        or state not in CLAIM_STATES
        or not isinstance(positioning, str)
        or not 0 < len(positioning) <= MAX_POSITIONING_LENGTH
    ):
        return None
    return {"state": state, "positioning": positioning, **CLAIM_BOUNDARY_FIELDS}


def project_first_run_receipt(value: Any) -> dict[str, Any] | None:
    """Project one receipt onto its closed consumer view, or ``None`` on drift."""
    if not isinstance(value, Mapping):
        return None
    schema_version = value.get("schema_version")
    verdict = value.get("verdict")
    budget_state = value.get("budget_state")
    verification_state = value.get("verification_state")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version < 1
        or verdict not in RECEIPT_VERDICTS
        or budget_state not in BUDGET_STATES
        or verification_state not in VERIFICATION_STATES
    ):
        return None
    projected: dict[str, Any] = {
        "schema_version": schema_version,
        "verdict": verdict,
        "budget_state": budget_state,
        "verification_state": verification_state,
    }
    if "claims" in value:
        claims = _claims(value["claims"])
        if claims is None:
            return None
        projected["claims"] = claims
    return projected


def first_run_receipt_output_schema() -> dict[str, Any]:
    """Return a fresh closed JSON Schema for the bounded receipt projection."""
    return {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "minimum": 1},
            "verdict": {"type": "string", "enum": list(RECEIPT_VERDICTS)},
            "budget_state": {"type": "string", "enum": list(BUDGET_STATES)},
            "verification_state": {"type": "string", "enum": list(VERIFICATION_STATES)},
            "claims": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "state": {"type": "string", "enum": list(CLAIM_STATES)},
                    "positioning": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_POSITIONING_LENGTH,
                    },
                    **{key: {"const": expected} for key, expected in CLAIM_BOUNDARY_FIELDS.items()},
                },
                "required": ["state", "positioning", *CLAIM_BOUNDARY_FIELDS],
            },
        },
        "required": ["schema_version", "verdict", "budget_state", "verification_state"],
    }
