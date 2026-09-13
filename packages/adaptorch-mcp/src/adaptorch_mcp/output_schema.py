from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, Final
from urllib.parse import urlsplit

from adaptorch_mcp.correctness_wall_output import project_correctness_wall
from adaptorch_mcp.discovery_output import project_capabilities as _project_capabilities
from adaptorch_mcp.discovery_output import project_catalog as project_catalog
from adaptorch_mcp.discovery_output import project_server_info as project_server_info
from adaptorch_mcp.first_run_receipt_output import project_first_run_receipt
from adaptorch_mcp.orchestration_value_output import project_orchestration_value
from adaptorch_mcp.projection_values import project_scalars as _project_scalars
from adaptorch_mcp.run_output import project_run_scalars

MAX_ROUTING_STAGES: Final = 64
MAX_ROUTING_STAGE_WIDTH: Final = 256
MAX_ROUTING_REASON_LENGTH: Final = 512
_ROUTING_FEATURE_KEYS: Final = frozenset(
    {
        "width",
        "width_mode",
        "critical_depth",
        "coupling_density",
        "parallel_ratio",
        "node_count",
        "edge_count",
        "feature_schema_version",
        "critical_depth_semantics",
        "structural_depth",
        "token_weighted_critical_path",
        "legacy_critical_path_depth",
    }
)
_ARTIFACT_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_ARTIFACT_URI_SCHEMES: Final = frozenset({"adaptorch", "gs", "https", "s3"})


def _is_artifact_reference(value: str) -> bool:
    if value.startswith("/"):
        return True
    parsed = urlsplit(value)
    return parsed.scheme in _ARTIFACT_URI_SCHEMES and bool(parsed.path or parsed.netloc)


def _project_artifact_map(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    references: dict[str, str] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or _ARTIFACT_NAME.fullmatch(key) is None
            or not isinstance(item, str)
            or not _is_artifact_reference(item)
        ):
            return None
        references[key] = item
    return references


def _project_run(value: Mapping[str, Any]) -> dict[str, Any] | None:
    projected = project_run_scalars(value)
    if projected is None:
        return None
    if "artifact_urls" in value:
        artifact_urls = _project_artifact_map(value["artifact_urls"])
        if artifact_urls is None:
            return None
        return {**projected, "artifact_urls": artifact_urls}
    return projected


def _project_get_run(value: Mapping[str, Any]) -> dict[str, Any] | None:
    projected = _project_run(value)
    if projected is None:
        return None
    if "correctness_wall" in value:
        projected["correctness_wall"] = project_correctness_wall(value["correctness_wall"])
    if "first_run_receipt" in value:
        # A malformed receipt projects to null rather than voiding the run
        # summary: the consumer still needs status, but must never receive an
        # unvalidated verdict.
        projected["first_run_receipt"] = project_first_run_receipt(value["first_run_receipt"])
    return projected


def _project_routing_stages(value: Any) -> list[list[str]] | None:
    if not isinstance(value, list) or len(value) > MAX_ROUTING_STAGES:
        return None
    stages: list[list[str]] = []
    for stage in value:
        if not isinstance(stage, list) or len(stage) > MAX_ROUTING_STAGE_WIDTH:
            return None
        if not all(isinstance(item, str) and item for item in stage):
            return None
        stages.append(list(stage))
    return stages


def _project_route_topology(value: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project the local router decision plus its cost/evidence advisory."""
    topology = value.get("topology")
    reason = value.get("reason")
    features = value.get("features")
    stages = _project_routing_stages(value.get("stages"))
    if (
        not isinstance(topology, str)
        or not topology
        or not isinstance(reason, str)
        or not 0 < len(reason) <= MAX_ROUTING_REASON_LENGTH
        or stages is None
        or not isinstance(features, Mapping)
        or bool(set(features) - _ROUTING_FEATURE_KEYS)
    ):
        return None
    projected_features = _project_scalars(features, _ROUTING_FEATURE_KEYS)
    if projected_features is None:
        return None
    projected: dict[str, Any] = {
        "topology": topology,
        "reason": reason,
        "stages": stages,
        "features": projected_features,
    }
    if "orchestration_value" in value:
        advisory = project_orchestration_value(value["orchestration_value"])
        if advisory is None:
            return None
        projected["orchestration_value"] = advisory
    return projected


def _project_artifacts(value: Mapping[str, Any]) -> dict[str, Any] | None:
    run_id = value.get("run_id")
    if not isinstance(run_id, str):
        return None
    raw_artifacts = value.get("artifacts")
    artifacts: dict[str, str] | list[str] | None = _project_artifact_map(raw_artifacts)
    if (
        artifacts is None
        and isinstance(raw_artifacts, list)
        and all(isinstance(item, str) and _is_artifact_reference(item) for item in raw_artifacts)
    ):
        artifacts = list(raw_artifacts)
    if artifacts is None:
        return None
    return {"run_id": run_id, "artifacts": artifacts}


def _project_run_list(value: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = _project_scalars(value, frozenset({"total", "page", "page_size", "has_next"}))
    items = value.get("items")
    if metadata is None or not isinstance(items, list):
        return None
    projected_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            return None
        projected = _project_run(item)
        if projected is None:
            return None
        projected_items.append(projected)
    return {"items": projected_items, **metadata}


def _project_metrics(value: Mapping[str, Any]) -> dict[str, Any] | None:
    keys = frozenset(
        {"tool_calls", "tool_errors", "p50_latency_ms", "p95_latency_ms", "notification_failures"}
    )
    if not keys.issubset(value):
        return None
    projected = _project_scalars(value, keys)
    status_counts = value.get("status_counts")
    if (
        projected is None
        or not isinstance(status_counts, Mapping)
        or not all(
            isinstance(key, str) and isinstance(item, int) for key, item in status_counts.items()
        )
    ):
        return None
    projected["status_counts"] = dict(status_counts)
    return projected


def _project_usage(value: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project the tenant's own usage window; the control plane scopes it by key."""
    keys = frozenset(
        {
            "tenant_id",
            "plan_level",
            "period",
            "used",
            "limit",
            "remaining",
            "usage_percentage",
        }
    )
    if not {"used", "limit"}.issubset(value):
        return None
    return _project_scalars(value, keys)


_Projector = Callable[[Mapping[str, Any]], dict[str, Any] | None]
_PROJECTORS: Final[dict[str, _Projector]] = {
    "adaptorch_run": _project_run,
    "adaptorch_get_run": _project_get_run,
    "adaptorch_get_artifacts": _project_artifacts,
    "adaptorch_list_runs": _project_run_list,
    "adaptorch_cancel_run": _project_run,
    "adaptorch_route_topology": _project_route_topology,
    "adaptorch_server_metrics": _project_metrics,
    "adaptorch_capabilities": _project_capabilities,
    "adaptorch_usage": _project_usage,
    "adaptorch_plan_catalog": project_catalog,
}


def project_tool_output(tool_name: str, value: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project one decoded tool payload onto its explicit public schema."""
    projector = _PROJECTORS.get(tool_name)
    return projector(value) if projector is not None else None
