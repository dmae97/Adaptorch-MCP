from __future__ import annotations

import hmac
import ipaddress
import os
from collections.abc import Mapping
from typing import Final, Literal
from urllib.parse import urlparse

ExposureProfile = Literal["remote", "full"]

REMOTE_EXPOSURE_PROFILE: Final[ExposureProfile] = "remote"
FULL_EXPOSURE_PROFILE: Final[ExposureProfile] = "full"
EXPOSURE_PROFILE_ENV: Final = "ADAPTORCH_MCP_EXPOSURE_PROFILE"
ALLOW_INSECURE_ENV: Final = "ADAPTORCH_MCP_ALLOW_INSECURE_CONTROL_PLANE"
_TRUTHY: Final = frozenset({"1", "true", "yes", "on"})


def resolve_exposure_profile(
    env: Mapping[str, str] | None = None,
) -> ExposureProfile:
    """Return the fail-closed MCP exposure profile."""
    resolved_env = os.environ if env is None else env
    value = resolved_env.get(EXPOSURE_PROFILE_ENV, REMOTE_EXPOSURE_PROFILE).strip().lower()
    if value in {"", REMOTE_EXPOSURE_PROFILE}:
        return REMOTE_EXPOSURE_PROFILE
    if value == FULL_EXPOSURE_PROFILE:
        return FULL_EXPOSURE_PROFILE
    raise ValueError(f"{EXPOSURE_PROFILE_ENV} must be 'remote' or 'full'")


def insecure_control_plane_allowed(env: Mapping[str, str] | None = None) -> bool:
    """Return whether explicit development-only plaintext transport is enabled."""
    resolved_env = os.environ if env is None else env
    return resolved_env.get(ALLOW_INSECURE_ENV, "").strip().lower() in _TRUTHY


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_control_plane_url(value: str, *, allow_insecure: bool) -> str:
    """Validate a control-plane URL without resolving or disclosing credentials."""
    stripped = value.strip()
    parsed = urlparse(stripped)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("control-plane URL must be http(s) with a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("control-plane URL must not include credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("control-plane URL has an invalid port") from exc
    if port is not None and port < 1:
        raise ValueError("control-plane URL has an invalid port")
    if (
        parsed.scheme.lower() == "http"
        and not _is_loopback_host(parsed.hostname)
        and not allow_insecure
    ):
        raise ValueError(
            f"remote HTTP is disabled; use HTTPS or set {ALLOW_INSECURE_ENV}=1 for development"
        )
    return stripped


def validate_http_binding(host: str) -> None:
    """Reject plaintext MCP HTTP listeners outside the loopback interface."""
    normalized = host.strip().removeprefix("[").removesuffix("]")
    if not _is_loopback_host(normalized):
        raise ValueError("MCP HTTP host must be an exact loopback address")


def validate_separate_tokens(upstream_token: str, client_token: str) -> None:
    """Require non-empty, role-separated bearer tokens for HTTP transport."""
    upstream = upstream_token.strip()
    client = client_token.strip()
    if not upstream:
        raise ValueError("upstream control-plane token is required")
    if not client:
        raise ValueError("client-facing MCP HTTP token is required")
    if hmac.compare_digest(upstream, client):
        raise ValueError("client-facing MCP HTTP token must differ from upstream token")
