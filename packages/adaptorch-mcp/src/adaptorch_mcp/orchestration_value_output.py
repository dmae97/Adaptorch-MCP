"""Bounded projection of the engine's orchestration-value advisory.

The engine decides; the wrapper only republishes a closed, bounded view of
what it decided. Anything that does not match the engine's declared vocabulary
— an unknown verdict, a mutated claim boundary, an unbounded reason string —
is rejected instead of forwarded, so a drifting or hostile parent cannot smuggle
a correctness claim through the public surface.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

MAX_REASON_LENGTH: Final = 512
MAX_TOPOLOGY_LENGTH: Final = 64

# Kept literal so the wrapper still validates advisories from engines that
# predate the exported constants. test_engine_algorithm_parity asserts equality
# with adaptorch.orchestration_value whenever the installed engine exports them.
ORCHESTRATION_VALUE_VERDICTS: Final[tuple[str, ...]] = (
    "no_extra_spend",
    "structural_spend",
    "replication_unproven",
    "replication_supported",
    "replication_rejected",
)
ORCHESTRATION_VALUE_ACTIONS: Final[tuple[str, ...]] = (
    "proceed",
    "measure_first",
    "downshift",
)
CLAIM_BOUNDARY_FIELDS: Final[dict[str, bool]] = {
    "is_correctness_proof": False,
    "is_active_selector": False,
    "is_cost_model_estimate": True,
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def _positive_number(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0.0 else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 1 else None


def _optional_cost(value: Any) -> tuple[bool, float | None]:
    """Return ``(valid, cost)``; ``None`` means the engine priced nothing."""
    if value is None:
        return True, None
    number = _number(value)
    if number is None or number < 0.0:
        return False, None
    return True, number


def _optional_unit_interval(value: Any) -> tuple[bool, float | None]:
    if value is None:
        return True, None
    number = _number(value)
    if number is None or not 0.0 <= number <= 1.0:
        return False, None
    return True, number


def _bounded_text(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str) or not 0 < len(value) <= max_length:
        return None
    return value


def _claim_boundary(value: Any) -> dict[str, bool] | None:
    if not isinstance(value, Mapping) or not all(
        value.get(key) is expected for key, expected in CLAIM_BOUNDARY_FIELDS.items()
    ):
        return None
    return dict(CLAIM_BOUNDARY_FIELDS)


def project_orchestration_value(value: Any) -> dict[str, Any] | None:
    """Project one advisory onto its closed public view, or ``None`` on drift."""
    if not isinstance(value, Mapping):
        return None
    verdict = value.get("verdict")
    action = value.get("recommended_action")
    measured = value.get("quality_gain_measured")
    if (
        verdict not in ORCHESTRATION_VALUE_VERDICTS
        or action not in ORCHESTRATION_VALUE_ACTIONS
        or not isinstance(measured, bool)
    ):
        return None

    reason = _bounded_text(value.get("reason"), max_length=MAX_REASON_LENGTH)
    topology = _bounded_text(value.get("topology"), max_length=MAX_TOPOLOGY_LENGTH)
    baseline_topology = _bounded_text(
        value.get("baseline_topology"), max_length=MAX_TOPOLOGY_LENGTH
    )
    cost_ratio = _positive_number(value.get("cost_ratio"))
    latency_ratio = _positive_number(value.get("latency_ratio"))
    estimated_tokens = _positive_int(value.get("estimated_total_tokens"))
    baseline_tokens = _positive_int(value.get("baseline_total_tokens"))
    claim_boundary = _claim_boundary(value.get("claim_boundary"))
    cost_valid, estimated_cost = _optional_cost(value.get("estimated_cost_usd"))
    baseline_cost_valid, baseline_cost = _optional_cost(value.get("baseline_cost_usd"))
    gain_valid, measured_gain = _optional_unit_interval(value.get("measured_quality_gain"))
    bar_valid, minimum_gain = _optional_unit_interval(value.get("min_quality_gain"))
    if (
        reason is None
        or topology is None
        or baseline_topology is None
        or cost_ratio is None
        or latency_ratio is None
        or estimated_tokens is None
        or baseline_tokens is None
        or claim_boundary is None
        or not (cost_valid and baseline_cost_valid and gain_valid and bar_valid)
        or (measured_gain is not None) is not measured
    ):
        return None

    return {
        "verdict": verdict,
        "recommended_action": action,
        "reason": reason,
        "topology": topology,
        "baseline_topology": baseline_topology,
        "cost_ratio": cost_ratio,
        "latency_ratio": latency_ratio,
        "estimated_total_tokens": estimated_tokens,
        "baseline_total_tokens": baseline_tokens,
        "estimated_cost_usd": estimated_cost,
        "baseline_cost_usd": baseline_cost,
        "quality_gain_measured": measured,
        "measured_quality_gain": measured_gain,
        "min_quality_gain": minimum_gain,
        "claim_boundary": claim_boundary,
    }
