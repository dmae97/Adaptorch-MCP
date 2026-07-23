from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, Final
from urllib.parse import urlsplit

from adaptorch_mcp.correctness_wall_output import RUN_SCALAR_KEYS, project_correctness_wall

_PLAN_SCALAR_KEYS: Final = frozenset(
    {"level", "name", "positioning", "monthly_price_usd", "monthly_calls", "badge", "cta"}
)
_ARTIFACT_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_ARTIFACT_URI_SCHEMES: Final = frozenset({"adaptorch", "gs", "https", "s3"})


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _project_scalars(value: Mapping[str, Any], keys: frozenset[str]) -> dict[str, Any] | None:
    projected: dict[str, Any] = {}
    for key in keys:
        if key not in value:
            continue
        item = value[key]
        if not _is_scalar(item):
            return None
        projected[key] = item
    return projected


def _project_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _is_artifact_reference(value: str) -> bool:
    if value.startswith("/"):
        return True
    parsed = urlsplit(value)
    return parsed.scheme in _ARTIFACT_URI_SCHEMES and bool(parsed.path or parsed.netloc)


def _project_artifact_map(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str)
        and _ARTIFACT_NAME.fullmatch(key) is not None
        and isinstance(item, str)
        and _is_artifact_reference(item)
        for key, item in value.items()
    ):
        return None
    return dict(value)


def _project_run(value: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(value.get("run_id"), str) or not isinstance(value.get("status"), str):
        return None
    projected = _project_scalars(value, RUN_SCALAR_KEYS)
    if projected is None:
        return None
    if "artifact_urls" in value:
        artifact_urls = _project_artifact_map(value["artifact_urls"])
        if artifact_urls is None:
            return None
        projected["artifact_urls"] = artifact_urls
    return projected


def _project_get_run(value: Mapping[str, Any]) -> dict[str, Any] | None:
    projected = _project_run(value)
    if projected is None:
        return None
    if "correctness_wall" in value:
        projected["correctness_wall"] = project_correctness_wall(value["correctness_wall"])
    return projected


def _project_artifacts(value: Mapping[str, Any]) -> dict[str, Any] | None:
    run_id = value.get("run_id")
    if not isinstance(run_id, str):
        return None
    raw_artifacts = value.get("artifacts")
    artifacts: dict[str, str] | list[str] | None = _project_artifact_map(raw_artifacts)
    if artifacts is None and isinstance(raw_artifacts, list) and all(
        isinstance(item, str) and _is_artifact_reference(item) for item in raw_artifacts
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
    if projected is None or not isinstance(status_counts, Mapping) or not all(
        isinstance(key, str) and isinstance(item, int) for key, item in status_counts.items()
    ):
        return None
    projected["status_counts"] = dict(status_counts)
    return projected


def _project_plan(value: Mapping[str, Any]) -> dict[str, Any] | None:
    projected = _project_scalars(value, _PLAN_SCALAR_KEYS)
    features = _project_string_list(value.get("features"))
    if projected is None or features is None:
        return None
    projected["features"] = features
    return projected


def project_catalog(value: Mapping[str, Any]) -> dict[str, Any] | None:
    scalar_keys = frozenset({"schemaVersion", "catalogVersion", "billingCycle", "currency"})
    projected = _project_scalars(value, scalar_keys)
    sources = _project_string_list(value.get("sourceOfTruth"))
    notes = _project_string_list(value.get("notes"))
    plans = value.get("plans")
    if projected is None or sources is None or notes is None or not isinstance(plans, list):
        return None
    projected_plans: list[dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, Mapping):
            return None
        projected_plan = _project_plan(plan)
        if projected_plan is None:
            return None
        projected_plans.append(projected_plan)
    return {**projected, "sourceOfTruth": sources, "plans": projected_plans, "notes": notes}


def _project_capabilities(value: Mapping[str, Any]) -> dict[str, Any] | None:
    synthesis_modes = _project_string_list(value.get("synthesis_modes"))
    connectors = _project_string_list(value.get("connectors"))
    raw_catalog = value.get("cloud_plan_catalog")
    raw_server = value.get("server_capabilities")
    if (
        synthesis_modes is None
        or connectors is None
        or not isinstance(raw_catalog, Mapping)
        or not isinstance(raw_server, Mapping)
    ):
        return None
    catalog = project_catalog(raw_catalog)
    server_keys = ("tools", "resources", "prompts", "logging")
    if catalog is None or not all(isinstance(raw_server.get(key), bool) for key in server_keys):
        return None
    return {
        "synthesis_modes": synthesis_modes,
        "connectors": connectors,
        "cloud_plan_catalog": catalog,
        "server_capabilities": {
            **{key: raw_server[key] for key in server_keys},
            "completions": False,
            "verification_commands_enabled": False,
        },
    }


def project_server_info(value: Mapping[str, Any]) -> dict[str, Any] | None:
    protocol_version = value.get("protocolVersion")
    server_info = value.get("serverInfo")
    capabilities = value.get("capabilities")
    if (
        not isinstance(protocol_version, str)
        or not isinstance(server_info, Mapping)
        or not isinstance(server_info.get("name"), str)
        or not isinstance(server_info.get("version"), str)
        or not isinstance(capabilities, Mapping)
    ):
        return None
    allowed_capabilities = {
        key: capabilities[key]
        for key in ("tools", "resources", "prompts", "logging")
        if isinstance(capabilities.get(key), Mapping)
    }
    return {
        "protocolVersion": protocol_version,
        "capabilities": allowed_capabilities,
        "serverInfo": {"name": server_info["name"], "version": server_info["version"]},
        "initialized": value.get("initialized") is True,
        "shutdownReceived": value.get("shutdownReceived") is True,
        "logLevel": value.get("logLevel") if isinstance(value.get("logLevel"), str) else "info",
    }


_Projector = Callable[[Mapping[str, Any]], dict[str, Any] | None]
_PROJECTORS: Final[dict[str, _Projector]] = {
    "adaptorch_run": _project_run,
    "adaptorch_get_run": _project_get_run,
    "adaptorch_get_artifacts": _project_artifacts,
    "adaptorch_list_runs": _project_run_list,
    "adaptorch_cancel_run": _project_run,
    "adaptorch_server_metrics": _project_metrics,
    "adaptorch_capabilities": _project_capabilities,
    "adaptorch_plan_catalog": project_catalog,
}


def project_tool_output(tool_name: str, value: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project one decoded tool payload onto its explicit public schema."""
    projector = _PROJECTORS.get(tool_name)
    return projector(value) if projector is not None else None
