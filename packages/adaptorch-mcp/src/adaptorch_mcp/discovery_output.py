"""Engine-declared discovery views; no local algorithm or execution is advertised."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from adaptorch_mcp.projection_values import project_scalars, project_string_list

_PLAN_SCALAR_KEYS: Final = frozenset(
    {"level", "name", "positioning", "monthly_price_usd", "monthly_calls", "badge", "cta"}
)


def _project_plan(value: Mapping[str, Any]) -> dict[str, Any] | None:
    projected = project_scalars(value, _PLAN_SCALAR_KEYS)
    features = project_string_list(value.get("features"))
    if projected is None or features is None:
        return None
    projected["features"] = features
    return projected


def project_catalog(value: Mapping[str, Any]) -> dict[str, Any] | None:
    scalar_keys = frozenset({"schemaVersion", "catalogVersion", "billingCycle", "currency"})
    projected = project_scalars(value, scalar_keys)
    sources = project_string_list(value.get("sourceOfTruth"))
    notes = project_string_list(value.get("notes"))
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


def _project_string_map(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        return None
    return {str(key): str(item) for key, item in value.items()}


def _project_algorithm_surface(value: Mapping[str, Any]) -> dict[str, Any] | None:
    projected: dict[str, Any] = {}
    for key in (
        "supported_synthesis_modes",
        "topologies",
        "output_extractor_modes",
        "orchestration_value_verdicts",
        "orchestration_value_actions",
        "verifier_types",
        "verification_outcome_kinds",
        "verification_decisions",
        "evidence_causalities",
    ):
        if key not in value:
            continue
        items = project_string_list(value[key])
        if items is None:
            return None
        projected[key] = items
    if "deprecated_synthesis_mode_aliases" in value:
        aliases = _project_string_map(value["deprecated_synthesis_mode_aliases"])
        if aliases is None:
            return None
        projected["deprecated_synthesis_mode_aliases"] = aliases
    return projected


def project_capabilities(value: Mapping[str, Any]) -> dict[str, Any] | None:
    synthesis_modes = project_string_list(value.get("synthesis_modes"))
    connectors = project_string_list(value.get("connectors"))
    algorithm_surface = _project_algorithm_surface(value)
    raw_catalog = value.get("cloud_plan_catalog")
    raw_server = value.get("server_capabilities")
    if (
        synthesis_modes is None
        or connectors is None
        or algorithm_surface is None
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
        **algorithm_surface,
        "connectors": connectors,
        "cloud_plan_catalog": catalog,
        "server_capabilities": {
            **{key: raw_server[key] for key in server_keys},
            "completions": False,
            "verification_commands_enabled": False,
        },
    }


def project_server_info(value: Mapping[str, Any]) -> dict[str, Any] | None:
    protocol_version, server_info, capabilities = (
        value.get("protocolVersion"),
        value.get("serverInfo"),
        value.get("capabilities"),
    )
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
    initialized, shutdown = value.get("initialized"), value.get("shutdownReceived")
    return {
        "protocolVersion": protocol_version,
        "capabilities": allowed_capabilities,
        "serverInfo": {"name": server_info["name"], "version": server_info["version"]},
        "initialized": isinstance(initialized, bool) and initialized,
        "shutdownReceived": isinstance(shutdown, bool) and shutdown,
        "logLevel": value.get("logLevel") if isinstance(value.get("logLevel"), str) else "info",
    }
