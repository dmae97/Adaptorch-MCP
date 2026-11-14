"""Public routing DTOs only. The hosted engine owns selection and PESCO policies."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from adaptorch_client.models import (
    JSONMapping,
    JSONValue,
    PayloadResult,
    contract_error,
    require_array,
    require_object,
    stored_copy,
    string_at,
)
from adaptorch_client.orchestration_value import project_orchestration_value

ROUTING_TOOL_NAME = "adaptorch_route_topology"
ROUTING_ARGUMENTS = frozenset(
    {
        "subtasks",
        "dependencies",
        "prefer_ensemble_singleton",
        "model",
        "measured_quality_gain",
        "min_quality_gain",
    }
)
_FEATURES = frozenset(
    {
        "feature_schema_version",
        "critical_depth_semantics",
        "width",
        "width_mode",
        "critical_depth",
        "structural_depth",
        "unit_work_parallelism",
        "token_weighted_critical_path",
        "legacy_critical_path_depth",
        "coupling_density",
        "parallel_ratio",
        "node_count",
        "edge_count",
    }
)
_PESCO_FIELDS = frozenset(
    {
        "schema",
        "mode",
        "state",
        "baseline_topology",
        "selected_topology",
        "changed",
        "allocation_verified",
        "alpha_spent_by_route",
        "execution_authorized",
        "is_correctness_proof",
        "error_class",
    }
)
_PANEL_FIELDS = frozenset(
    {
        "expected_pairs",
        "received_pairs",
        "unresolved_pairs",
        "requirements",
        "minimum_evidence_slack",
        "cost_headroom_micros",
        "latency_headroom_ms",
    }
)


def routing_arguments(payload: Mapping[str, JSONValue]) -> JSONMapping:
    if set(payload) - ROUTING_ARGUMENTS:
        raise ValueError("unsupported routing argument")
    result = dict(payload)
    for name, maximum in (("subtasks", 256), ("dependencies", 4096)):
        values = result.get(name, [] if name == "dependencies" else None)
        if (
            not isinstance(values, list)
            or len(values) > maximum
            or name == "subtasks"
            and not values
            or any(not isinstance(item, dict) for item in values)
        ):
            raise ValueError(f"{name} must be a bounded array of objects")
    result.setdefault("prefer_ensemble_singleton", False)
    preference = result["prefer_ensemble_singleton"]
    if preference is not None and type(preference) is not bool:
        raise ValueError("prefer_ensemble_singleton must be boolean or null")
    if "model" in result and not isinstance(result["model"], str):
        raise ValueError("model must be a string")
    for name in ("measured_quality_gain", "min_quality_gain"):
        if name in result:
            value = result[name]
            if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
    return result


def _scalars(value: Mapping[str, JSONValue], keys: frozenset[str]) -> JSONMapping:
    projected: JSONMapping = {}
    for key in keys & value.keys():
        item = value[key]
        if isinstance(item, list | dict):
            raise contract_error(key, "a scalar")
        if isinstance(item, float) and not math.isfinite(item):
            raise contract_error(key, "a finite scalar")
        if isinstance(item, str) and (len(item) > 2048 or not item.isprintable()):
            raise contract_error(key, "a bounded printable string")
        projected[key] = item
    return projected


def project_pesco(payload: Mapping[str, JSONValue], topology: str) -> JSONMapping:
    projected = _scalars(payload, _PESCO_FIELDS)
    if (
        projected.get("schema") != "pesco.initial-routing/v1"
        or projected.get("mode") != "advisory"
        or projected.get("selected_topology") != topology
    ):
        raise contract_error("pesco", "scope-matched initial routing advice")
    for name in ("alpha_spent_by_route", "execution_authorized", "is_correctness_proof"):
        if projected.get(name) is not False:
            raise contract_error(f"pesco.{name}", "false")
    for name in ("changed", "allocation_verified"):
        if type(projected.get(name)) is not bool:
            raise contract_error(f"pesco.{name}", "a boolean")
    for name in ("state", "baseline_topology"):
        string_at(projected, name, "pesco")
    if projected["changed"] != (projected["baseline_topology"] != topology):
        raise contract_error("pesco.changed", "consistent topology evidence")
    if "checks" in payload:
        checks = require_array(payload["checks"], "pesco.checks")
        if len(checks) > 16:
            raise contract_error("pesco.checks", "at most 16 guards")
        clean: list[JSONValue] = []
        for item in checks:
            check = require_object(item, "pesco.checks[]")
            name = string_at(check, "check", "pesco.checks[]")
            if len(name) > 64 or type(check.get("passed")) is not bool:
                raise contract_error("pesco.checks[]", "a bounded guard and boolean")
            clean.append({"check": name, "passed": check["passed"]})
        projected["checks"] = clean
    if "panel" in payload:
        panel = _scalars(require_object(payload["panel"], "pesco.panel"), _PANEL_FIELDS)
        if any(
            v is not None and (isinstance(v, bool) or not isinstance(v, int | float))
            for v in panel.values()
        ):
            raise contract_error("pesco.panel", "numeric evidence only")
        projected["panel"] = panel
    return projected


@dataclass(frozen=True, slots=True)
class TopologyAdvice(PayloadResult):
    """Scheduling advice, not execution authority or a correctness certificate."""

    topology: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, JSONValue]) -> Self:
        payload = dict(payload)
        topology = string_at(payload, "topology", "")
        reason = string_at(payload, "reason", "")
        stages = require_array(payload.get("stages"), "stages")
        if not topology or len(topology) > 64 or not 0 < len(reason) <= 2048 or len(stages) > 256:
            raise contract_error("routing", "bounded routing advice")
        for stage in stages:
            nodes = require_array(stage, "stages[]")
            if len(nodes) > 256 or any(not isinstance(n, str) or len(n) > 256 for n in nodes):
                raise contract_error("stages[]", "bounded node IDs")
        record: JSONMapping = {
            "topology": topology,
            "reason": reason,
            "stages": stages,
            "features": _scalars(require_object(payload.get("features"), "features"), _FEATURES),
        }
        if "pesco" in payload:
            record["pesco"] = project_pesco(require_object(payload["pesco"], "pesco"), topology)
        if "orchestration_value" in payload:
            advisory = project_orchestration_value(payload["orchestration_value"])
            if advisory is None or advisory["topology"] != topology:
                raise contract_error("orchestration_value", "scope-matched cost advice")
            record["orchestration_value"] = advisory
        return cls(stored_copy(record), topology=topology)
