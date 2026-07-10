from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def format_diagnostics(payload: Mapping[str, Any]) -> str:
    """Format diagnostics without printing secret values."""
    packages = payload.get("packages", {})
    environment = payload.get("environment", {})
    token_vars = environment.get("tokens", {}) if isinstance(environment, Mapping) else {}
    config_vars = environment.get("config", {}) if isinstance(environment, Mapping) else {}
    control_plane = payload.get("controlPlane", {})

    lines = ["AdaptOrch MCP diagnostics", ""]
    python_info = payload.get("python", {})
    if isinstance(python_info, Mapping):
        lines.append(f"Python: {python_info.get('implementation')} {python_info.get('version')}")
    lines.extend((f"OK: {bool(payload.get('ok'))}", "", "Packages:"))
    if isinstance(packages, Mapping):
        for name, status in packages.items():
            if isinstance(status, Mapping):
                lines.append(
                    f"- {name}: importable={status.get('importable')} "
                    f"version={status.get('version') or 'unknown'}"
                )
    lines.extend(("", "Environment:"))
    if isinstance(token_vars, Mapping):
        for name, status in token_vars.items():
            set_flag = status.get("set") if isinstance(status, Mapping) else False
            lines.append(f"- {name}: set={set_flag}")
    if isinstance(config_vars, Mapping):
        for name, value in config_vars.items():
            lines.append(f"- {name}: {value}")
    lines.extend(("", "Control plane:"))
    if isinstance(control_plane, Mapping):
        for name in (
            "defaultBaseUrl",
            "envBaseUrl",
            "resolvedBaseUrl",
            "resolvedSource",
            "invalidEnvUrl",
            "policyValid",
            "envError",
            "policyError",
        ):
            value = control_plane.get(name)
            if value is not None:
                lines.append(f"- {name}: {value}")
    lines.extend(("", "Security:"))
    security = payload.get("security", {})
    if isinstance(security, Mapping):
        for name in (
            "exposureProfile",
            "profileValid",
            "algorithmExecutionBoundary",
            "localAlgorithmOraclesExposed",
            "remoteControlPlaneRequiresHttps",
            "insecureControlPlaneAllowed",
        ):
            lines.append(f"- {name}: {security.get(name)}")
    lines.extend(("", "Expected core MCP tools:"))
    for tool in payload.get("expectedTools", []):
        lines.append(f"- {tool}")
    return "\n".join(lines)
