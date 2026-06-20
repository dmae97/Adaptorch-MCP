from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import platform
import sys
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from adaptorch_mcp.cli import _CONTROL_PLANE_BASE_URL_ENV, _HOSTED_BASE_URL, _normalize_env_base_url

EXPECTED_CORE_TOOLS: tuple[str, ...] = (
    "adaptorch_run",
    "adaptorch_get_run",
    "adaptorch_get_artifacts",
    "adaptorch_list_runs",
    "adaptorch_get_traces",
    "adaptorch_cancel_run",
    "adaptorch_route_topology",
    "adaptorch_server_metrics",
    "adaptorch_capabilities",
    "adaptorch_plan_catalog",
)

_RUNTIME_PACKAGES: tuple[tuple[str, str], ...] = (
    ("adaptorch", "adaptorch"),
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
)

_TOKEN_ENV_VARS: tuple[str, ...] = (
    "ADAPTORCH_CONTROL_PLANE_TOKEN",
    "ADAPTORCH_MCP_HTTP_AUTH_TOKEN",
)

_CONFIG_ENV_VARS: tuple[str, ...] = (
    "ADAPTORCH_CONTROL_PLANE_BASE_URL",
    "ADAPTORCH_MCP_HTTP_HOST",
    "ADAPTORCH_MCP_HTTP_PORT",
    "ADAPTORCH_MCP_TIMEOUT_SECONDS",
)


def _package_status(import_name: str, distribution_name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(import_name)
    importable = spec is not None
    version: str | None
    try:
        version = importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        version = None
    return {"importable": importable, "version": version}


def _redact_url_userinfo(value: str) -> str:
    """Return a URL string with any embedded userinfo removed."""
    stripped = value.strip()
    try:
        parsed = urlsplit(stripped)
    except ValueError:
        return stripped
    if not parsed.username and not parsed.password:
        return stripped
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _config_env_value(name: str, value: str) -> str | None:
    if name == _CONTROL_PLANE_BASE_URL_ENV:
        stripped = value.strip()
        return _redact_url_userinfo(stripped) if stripped else None
    return value


def _env_status(env: Mapping[str, str]) -> dict[str, Any]:
    token_vars = {
        name: {"set": bool(env.get(name)), "length": len(env.get(name, "")) or None}
        for name in _TOKEN_ENV_VARS
    }
    config_vars: dict[str, str] = {}
    for name in _CONFIG_ENV_VARS:
        value = env.get(name)
        if not value:
            continue
        normalized = _config_env_value(name, value)
        if normalized:
            config_vars[name] = normalized
    return {"tokens": token_vars, "config": config_vars}


def _control_plane_status(env: Mapping[str, str]) -> dict[str, Any]:
    raw_env_base_url = env.get(_CONTROL_PLANE_BASE_URL_ENV)
    invalid_env_url = False
    env_error: str | None = None
    try:
        env_base_url = _normalize_env_base_url(raw_env_base_url)
    except ValueError as exc:
        invalid_env_url = True
        env_error = str(exc)
        env_base_url = None

    resolved_base_url = env_base_url or _HOSTED_BASE_URL
    return {
        "defaultBaseUrl": _HOSTED_BASE_URL,
        "envBaseUrl": _redact_url_userinfo(env_base_url) if env_base_url is not None else None,
        "resolvedBaseUrl": _redact_url_userinfo(resolved_base_url),
        "resolvedSource": "env" if env_base_url is not None else "hosted-default",
        "invalidEnvUrl": invalid_env_url,
        "envError": env_error,
    }


def collect_diagnostics(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return redacted runtime diagnostics for public support requests."""
    resolved_env = os.environ if env is None else env
    packages = {
        distribution_name: _package_status(import_name, distribution_name)
        for import_name, distribution_name in _RUNTIME_PACKAGES
    }
    return {
        "schemaVersion": "adaptorch_mcp.diagnostics.v1",
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "packages": packages,
        "environment": _env_status(resolved_env),
        "controlPlane": _control_plane_status(resolved_env),
        "expectedTools": list(EXPECTED_CORE_TOOLS),
        "ok": packages["adaptorch"]["importable"],
    }


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
    lines.append(f"OK: {bool(payload.get('ok'))}")
    lines.append("")
    lines.append("Packages:")
    if isinstance(packages, Mapping):
        for name, status in packages.items():
            if isinstance(status, Mapping):
                lines.append(
                    f"- {name}: importable={status.get('importable')} "
                    f"version={status.get('version') or 'unknown'}"
                )
    lines.append("")
    lines.append("Environment:")
    if isinstance(token_vars, Mapping):
        for name, status in token_vars.items():
            set_flag = status.get("set") if isinstance(status, Mapping) else False
            length = status.get("length") if isinstance(status, Mapping) else None
            length_label = f", length={length}" if length is not None else ""
            lines.append(f"- {name}: set={set_flag}{length_label}")
    if isinstance(config_vars, Mapping):
        for name, value in config_vars.items():
            lines.append(f"- {name}: {value}")
    lines.append("")
    lines.append("Control plane:")
    if isinstance(control_plane, Mapping):
        lines.append(f"- defaultBaseUrl: {control_plane.get('defaultBaseUrl')}")
        lines.append(f"- envBaseUrl: {control_plane.get('envBaseUrl')}")
        lines.append(f"- resolvedBaseUrl: {control_plane.get('resolvedBaseUrl')}")
        lines.append(f"- resolvedSource: {control_plane.get('resolvedSource')}")
        lines.append(f"- invalidEnvUrl: {bool(control_plane.get('invalidEnvUrl'))}")
        if control_plane.get("envError"):
            lines.append(f"- envError: {control_plane.get('envError')}")
    lines.append("")
    lines.append("Expected core MCP tools:")
    for tool in payload.get("expectedTools", []):
        lines.append(f"- {tool}")
    return "\n".join(lines)
