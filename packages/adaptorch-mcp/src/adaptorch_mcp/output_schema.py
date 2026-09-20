from __future__ import annotations

import math
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
        "unit_work_parallelism",
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


def _project_attempt_events(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or len(value) > 64:
        return None
    events: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        attempt = item.get("attempt")
        kind = _bounded_str(item.get("kind"), 64)
        delay = item.get("delay_seconds")
        if (
            isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or not 0 <= attempt <= 64
            or kind is None
            or isinstance(delay, bool)
            or not isinstance(delay, int | float)
            or not math.isfinite(delay)
            or delay < 0
        ):
            return None
        # A wait/cancel event legitimately carries no HTTP status, so null is
        # preserved rather than dropped: the engine's own record round-trips.
        status_code = item.get("status_code")
        if status_code is not None and (
            isinstance(status_code, bool)
            or not isinstance(status_code, int)
            or not 100 <= status_code <= 599
        ):
            return None
        events.append(
            {
                "attempt": attempt,
                "kind": kind,
                "status_code": status_code,
                "delay_seconds": delay,
            }
        )
    return events


def _project_recovery(value: Any) -> dict[str, Any] | None:
    """Bounded projection of the engine's client-side HTTP recovery records.

    Two shapes share this projector: ``connector_recovery`` is the per-call
    attempt trace (counters plus events) and ``recovery`` is the failure record
    (reason, outcome, next action). Absent keys stay absent — inventing a
    ``reason: null`` on a successful trace would report a failure that did not
    happen. Only allowlisted metadata crosses the remote profile; transport
    text and upstream bodies never do, and a malformed record drops the field
    rather than voiding the whole run summary.
    """
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        return None
    projected: dict[str, Any] = {"schema_version": 1}
    if "reason" in value:
        if value["reason"] not in _RECOVERY_REASONS:
            return None
        projected["reason"] = value["reason"]
    if "request_outcome" in value:
        if value["request_outcome"] not in _RECOVERY_OUTCOMES:
            return None
        projected["request_outcome"] = value["request_outcome"]
    for key in ("requests", "attempts", "retries", "omitted_events"):
        item = value.get(key)
        if item is None:
            continue
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 10000:
            return None
        projected[key] = item
    for key in ("retryable", "replay_safe", "new_run_safe"):
        item = value.get(key)
        if item is None:
            continue
        if not isinstance(item, bool):
            return None
        projected[key] = item
    status_code = value.get("status_code")
    if status_code is not None:
        if (
            isinstance(status_code, bool)
            or not isinstance(status_code, int)
            or not 100 <= status_code <= 599
        ):
            return None
        projected["status_code"] = status_code
    retry_after = value.get("retry_after_seconds")
    if retry_after is not None:
        if (
            isinstance(retry_after, bool)
            or not isinstance(retry_after, int | float)
            or not math.isfinite(retry_after)
            or retry_after < 0
        ):
            return None
        projected["retry_after_seconds"] = retry_after
    for key in ("run_id", "idempotency_key", "next_action"):
        item = value.get(key)
        if item is None:
            continue
        if key == "next_action":
            if item not in _RECOVERY_ACTIONS:
                return None
            projected[key] = item
        else:
            bounded = _bounded_str(item, 256)
            if bounded is None:
                return None
            projected[key] = bounded
    if "events" in value:
        events = _project_attempt_events(value["events"])
        if events is None:
            return None
        projected["events"] = events
    return projected


_CONSUMER_RECEIPT_ENUMS: Final[dict[str, frozenset[str]]] = {
    "verification_state": frozenset({"passed", "failed", "error", "not_run", "unknown"}),
    "budget_state": frozenset(
        {"within_cap", "cap_missing", "cap_untrusted", "cost_unknown", "cap_exceeded", "unknown"}
    ),
    "collection_status": frozenset({"complete", "pending", "blocked"}),
    "artifact_status": frozenset(
        {"available", "not_available", "not_requested", "pending", "blocked"}
    ),
}


def _project_consumer_receipt(value: Any) -> dict[str, Any] | None:
    """Bounded projection of the engine's consumer-facing collection receipt."""
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        return None
    projected: dict[str, Any] = {"schema_version": 1}
    for key, allowed in _CONSUMER_RECEIPT_ENUMS.items():
        item = value.get(key)
        projected[key] = item if isinstance(item, str) and item in allowed else "unknown"
    run_id = value.get("run_id")
    projected["run_id"] = _bounded_str(run_id, 256) if run_id is not None else None
    for key in ("headline", "headline_ko", "next_action", "next_action_ko"):
        item = value.get(key)
        bounded = _bounded_str(item, 512)
        if item is not None and bounded is None:
            return None
        if bounded is not None:
            projected[key] = bounded
    for key in ("correctness_guaranteed", "new_run_recommended"):
        # These may only publish False: a wrapper that lets the parent set them
        # would let a receipt overclaim what the product guarantees.
        item = value.get(key)
        if isinstance(item, bool) and not item:
            projected[key] = False
        elif item is not None or key in value:
            return None
        else:
            return None
    reason = value.get("recovery_reason")
    if reason is not None:
        if reason not in _RECOVERY_REASONS:
            return None
        projected["recovery_reason"] = reason
    status = value.get("execution_status")
    if status is not None:
        bounded = _bounded_str(status, 64)
        if bounded is None:
            return None
        projected["execution_status"] = bounded
    return projected


def _project_run(value: Mapping[str, Any]) -> dict[str, Any] | None:
    projected = project_run_scalars(value)
    if projected is None:
        return None
    if "artifact_urls" in value:
        artifact_urls = _project_artifact_map(value["artifact_urls"])
        if artifact_urls is None:
            return None
        projected["artifact_urls"] = dict(artifact_urls)
    # Stability fields are optional engine metadata; malformed objects drop the
    # field (never the run summary), matching the first_run_receipt contract.
    for key in ("recovery", "connector_recovery"):
        if key in value:
            projected[key] = _project_recovery(value[key])
    if "consumer_receipt" in value:
        projected["consumer_receipt"] = _project_consumer_receipt(value["consumer_receipt"])
    if "first_run_receipt" in value:
        projected["first_run_receipt"] = project_first_run_receipt(value["first_run_receipt"])
    return projected


def _project_get_run(value: Mapping[str, Any]) -> dict[str, Any] | None:
    projected = _project_run(value)
    if projected is None:
        return None
    if "correctness_wall" in value:
        projected["correctness_wall"] = project_correctness_wall(value["correctness_wall"])
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
