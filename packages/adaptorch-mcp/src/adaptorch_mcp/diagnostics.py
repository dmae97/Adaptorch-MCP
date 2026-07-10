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
from adaptorch_mcp.diagnostic_format import format_diagnostics
from adaptorch_mcp.security_policy import (
    ALLOW_INSECURE_ENV,
    EXPOSURE_PROFILE_ENV,
    insecure_control_plane_allowed,
    validate_control_plane_url,
)

__all__ = ["EXPECTED_CORE_TOOLS", "collect_diagnostics", "format_diagnostics"]

EXPECTED_CORE_TOOLS: tuple[str, ...] = (
    "adaptorch_run",
    "adaptorch_get_run",
    "adaptorch_get_artifacts",
    "adaptorch_list_runs",
    "adaptorch_cancel_run",
    "adaptorch_server_metrics",
    "adaptorch_capabilities",
    "adaptorch_plan_catalog",
)

_FULL_CORE_TOOLS: tuple[str, ...] = (
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
_CONTROL_PLANE_TOKEN_ENV = "ADAPTORCH_CONTROL_PLANE_TOKEN"
# Dashboard API-key contract: canonical ado_live_/ado_test_ plus legacy ak_ prefixes.
_RECOGNIZED_TOKEN_PREFIXES: tuple[str, ...] = ("ado_", "ak_")

_ALLOWED_ORIGINS_ENV = "ADAPTORCH_MCP_ALLOWED_ORIGINS"

_CONFIG_ENV_VARS: tuple[str, ...] = (
    "ADAPTORCH_CONTROL_PLANE_BASE_URL",
    _ALLOWED_ORIGINS_ENV,
    "ADAPTORCH_MCP_HTTP_HOST",
    "ADAPTORCH_MCP_HTTP_PORT",
    "ADAPTORCH_MCP_TIMEOUT_SECONDS",
    EXPOSURE_PROFILE_ENV,
    ALLOW_INSECURE_ENV,
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
    if name == _ALLOWED_ORIGINS_ENV:
        stripped = value.strip()
        if not stripped:
            return None
        return ",".join(_redact_url_userinfo(origin) for origin in stripped.split(","))
    return value


def _env_status(env: Mapping[str, str]) -> dict[str, Any]:
    token_vars: dict[str, dict[str, Any]] = {}
    for name in _TOKEN_ENV_VARS:
        value = env.get(name, "")
        status: dict[str, Any] = {"set": bool(value)}
        if name == _CONTROL_PLANE_TOKEN_ENV and value:
            status["formatRecognized"] = value.strip().startswith(_RECOGNIZED_TOKEN_PREFIXES)
        token_vars[name] = status
    config_vars: dict[str, str] = {}
    for name in _CONFIG_ENV_VARS:
        config_value = env.get(name)
        if not config_value:
            continue
        normalized = _config_env_value(name, config_value)
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
        raw_env_error = str(exc)
        env_error = (
            _redact_url_userinfo(raw_env_error)
            if "://" not in raw_env_error
            else f"{_CONTROL_PLANE_BASE_URL_ENV} is invalid"
        )
        env_base_url = None

    resolved_base_url = env_base_url or _HOSTED_BASE_URL
    allow_insecure = insecure_control_plane_allowed(env)
    policy_valid = not invalid_env_url
    policy_error = "control-plane environment URL is invalid" if invalid_env_url else None
    if policy_valid:
        try:
            validate_control_plane_url(resolved_base_url, allow_insecure=allow_insecure)
        except ValueError:
            policy_valid = False
            policy_error = "control-plane URL violates the transport security policy"
    return {
        "defaultBaseUrl": _HOSTED_BASE_URL,
        "envBaseUrl": _redact_url_userinfo(env_base_url) if env_base_url is not None else None,
        "resolvedBaseUrl": _redact_url_userinfo(resolved_base_url),
        "resolvedSource": "env" if env_base_url is not None else "hosted-default",
        "invalidEnvUrl": invalid_env_url,
        "envError": env_error,
        "policyValid": policy_valid,
        "policyError": policy_error,
    }


def _security_status(env: Mapping[str, str]) -> dict[str, Any]:
    raw_profile = env.get(EXPOSURE_PROFILE_ENV, "remote").strip().lower()
    profile_valid = raw_profile in {"", "remote", "full"}
    profile = "full" if raw_profile == "full" else "remote"
    allow_insecure = insecure_control_plane_allowed(env)
    return {
        "exposureProfile": profile,
        "profileValid": profile_valid,
        "algorithmExecutionBoundary": (
            "mixed-local-and-control-plane" if profile == "full" else "control-plane"
        ),
        "localAlgorithmOraclesExposed": profile == "full" and profile_valid,
        "remoteControlPlaneRequiresHttps": not allow_insecure,
        "insecureControlPlaneAllowed": allow_insecure,
        "httpTokensMustBeDistinct": True,
    }


def collect_diagnostics(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return redacted runtime diagnostics for public support requests."""
    resolved_env = os.environ if env is None else env
    packages = {
        distribution_name: _package_status(import_name, distribution_name)
        for import_name, distribution_name in _RUNTIME_PACKAGES
    }
    security = _security_status(resolved_env)
    control_plane = _control_plane_status(resolved_env)
    expected_tools = (
        _FULL_CORE_TOOLS
        if security["exposureProfile"] == "full" and security["profileValid"]
        else EXPECTED_CORE_TOOLS
    )
    return {
        "schemaVersion": "adaptorch_mcp.diagnostics.v2",
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
        "controlPlane": control_plane,
        "security": security,
        "expectedTools": list(expected_tools),
        "ok": (
            packages["adaptorch"]["importable"]
            and security["profileValid"]
            and not control_plane["invalidEnvUrl"]
            and control_plane["policyValid"]
        ),
    }
