"""Projection tests for the engine's orchestration-value advisory.

The wrapper republishes the engine's cost/evidence verdict and nothing else.
Every test here asks the same question from a different angle: can a drifting
or hostile parent get an unvalidated claim onto the public surface? The answer
must always be no — the projection returns ``None`` instead of forwarding.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from adaptorch_mcp.orchestration_value_output import (
    CLAIM_BOUNDARY_FIELDS,
    MAX_REASON_LENGTH,
    ORCHESTRATION_VALUE_ACTIONS,
    ORCHESTRATION_VALUE_VERDICTS,
    project_orchestration_value,
)
from adaptorch_mcp.output_schema import project_tool_output


def _advisory(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "verdict": "replication_unproven",
        "recommended_action": "measure_first",
        "reason": "replication cost is an empirical accuracy claim",
        "topology": "multi_model_ensemble",
        "baseline_topology": "sequential",
        "cost_ratio": 3.0,
        "latency_ratio": 1.0,
        "estimated_total_tokens": 1500,
        "baseline_total_tokens": 500,
        "estimated_cost_usd": 0.0015,
        "baseline_cost_usd": 0.0005,
        "quality_gain_measured": False,
        "measured_quality_gain": None,
        "min_quality_gain": None,
        "claim_boundary": dict(CLAIM_BOUNDARY_FIELDS),
    }
    payload.update(overrides)
    return payload


def _routing(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "topology": "multi_model_ensemble",
        "reason": "single-node DAG with ensemble preference enabled",
        "stages": [["v1"]],
        "features": {
            "width": 1,
            "width_mode": "approx",
            "critical_depth": 1.0,
            "coupling_density": 0.0,
            "parallel_ratio": 1.0,
            "node_count": 1,
            "edge_count": 0,
        },
        "orchestration_value": _advisory(),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Accepted shape
# --------------------------------------------------------------------------


def test_valid_advisory_round_trips_with_a_closed_key_set() -> None:
    projected = project_orchestration_value(_advisory())

    assert projected == _advisory()


@pytest.mark.parametrize("field", ["cost_ratio", "latency_ratio", "estimated_cost_usd"])
def test_oversized_numeric_values_fail_closed(field: str) -> None:
    assert project_orchestration_value(_advisory(**{field: 10**400})) is None


def test_projection_drops_unknown_keys_the_parent_adds() -> None:
    projected = project_orchestration_value(_advisory(selected_model="gpt-4o"))

    assert projected is not None
    assert "selected_model" not in projected


def test_measured_advisory_keeps_the_gain_and_the_bar() -> None:
    projected = project_orchestration_value(
        _advisory(
            verdict="replication_supported",
            recommended_action="proceed",
            quality_gain_measured=True,
            measured_quality_gain=0.12,
            min_quality_gain=0.05,
        )
    )

    assert projected is not None
    assert projected["measured_quality_gain"] == pytest.approx(0.12)
    assert projected["min_quality_gain"] == pytest.approx(0.05)


def test_unpriced_model_projects_null_costs() -> None:
    projected = project_orchestration_value(
        _advisory(estimated_cost_usd=None, baseline_cost_usd=None)
    )

    assert projected is not None
    assert projected["estimated_cost_usd"] is None
    assert projected["baseline_cost_usd"] is None


# --------------------------------------------------------------------------
# Fail-closed rejection
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"verdict": "definitely_worth_it"}, id="unknown-verdict"),
        pytest.param({"recommended_action": "escalate"}, id="unknown-action"),
        pytest.param({"cost_ratio": 0}, id="non-positive-cost-ratio"),
        pytest.param({"cost_ratio": math.inf}, id="non-finite-cost-ratio"),
        pytest.param({"latency_ratio": "3x"}, id="non-numeric-latency"),
        pytest.param({"estimated_total_tokens": 0}, id="zero-tokens"),
        pytest.param({"baseline_total_tokens": True}, id="bool-as-token-count"),
        pytest.param({"estimated_cost_usd": -1.0}, id="negative-cost"),
        pytest.param({"measured_quality_gain": 1.5}, id="gain-out-of-range"),
        pytest.param({"min_quality_gain": -0.1}, id="bar-out-of-range"),
        pytest.param({"quality_gain_measured": "yes"}, id="non-bool-measured-flag"),
        pytest.param({"reason": ""}, id="empty-reason"),
        pytest.param({"topology": 3}, id="non-string-topology"),
        pytest.param({"baseline_topology": ""}, id="empty-baseline-topology"),
    ],
)
def test_malformed_advisory_fields_are_rejected(overrides: dict[str, Any]) -> None:
    assert project_orchestration_value(_advisory(**overrides)) is None


def test_reason_longer_than_the_bound_is_rejected() -> None:
    assert project_orchestration_value(_advisory(reason="x" * (MAX_REASON_LENGTH + 1))) is None


@pytest.mark.parametrize("field", sorted(CLAIM_BOUNDARY_FIELDS))
def test_mutated_claim_boundary_is_rejected(field: str) -> None:
    boundary = dict(CLAIM_BOUNDARY_FIELDS)
    boundary[field] = not boundary[field]

    assert project_orchestration_value(_advisory(claim_boundary=boundary)) is None


def test_missing_claim_boundary_is_rejected() -> None:
    payload = _advisory()
    del payload["claim_boundary"]

    assert project_orchestration_value(payload) is None


def test_measured_flag_must_agree_with_the_reported_gain() -> None:
    """A parent cannot claim a measurement it did not supply, or hide one."""
    assert project_orchestration_value(_advisory(quality_gain_measured=True)) is None
    assert (
        project_orchestration_value(
            _advisory(quality_gain_measured=False, measured_quality_gain=0.3)
        )
        is None
    )


@pytest.mark.parametrize("value", [None, "advisory", 3, ["verdict"]])
def test_non_mapping_advisory_is_rejected(value: Any) -> None:
    assert project_orchestration_value(value) is None


# --------------------------------------------------------------------------
# Tool-level projection
# --------------------------------------------------------------------------


def test_route_topology_output_carries_the_projected_advisory() -> None:
    projected = project_tool_output("adaptorch_route_topology", _routing())

    assert projected is not None
    assert projected["topology"] == "multi_model_ensemble"
    assert projected["orchestration_value"] == _advisory()


def test_route_topology_output_tolerates_engines_without_the_advisory() -> None:
    payload = _routing()
    del payload["orchestration_value"]

    projected = project_tool_output("adaptorch_route_topology", payload)

    assert projected is not None
    assert "orchestration_value" not in projected


def test_route_topology_output_rejects_a_malformed_advisory() -> None:
    payload = _routing(orchestration_value=_advisory(verdict="great_value"))

    assert project_tool_output("adaptorch_route_topology", payload) is None


def test_route_topology_output_rejects_unknown_routing_features() -> None:
    features = dict(_routing()["features"])
    features["internal_model_scores"] = 0.9

    assert project_tool_output("adaptorch_route_topology", _routing(features=features)) is None


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"topology": ""}, id="empty-topology"),
        pytest.param({"stages": [["v1", 2]]}, id="non-string-stage-member"),
        pytest.param({"stages": "v1"}, id="stages-not-a-list"),
        pytest.param({"features": []}, id="features-not-a-mapping"),
        pytest.param({"reason": ""}, id="empty-reason"),
    ],
)
def test_route_topology_output_rejects_malformed_decisions(overrides: dict[str, Any]) -> None:
    assert project_tool_output("adaptorch_route_topology", _routing(**overrides)) is None


def test_vocabularies_are_non_empty_and_disjoint() -> None:
    assert ORCHESTRATION_VALUE_VERDICTS
    assert ORCHESTRATION_VALUE_ACTIONS
    assert not set(ORCHESTRATION_VALUE_VERDICTS) & set(ORCHESTRATION_VALUE_ACTIONS)
