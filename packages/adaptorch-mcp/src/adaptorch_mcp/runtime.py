# mypy: disable-error-code="import-not-found,no-any-return"
# pyright: reportMissingImports=false
from __future__ import annotations

import hmac
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from adaptorch.mcp_server import (
    build_parser as build_parent_parser,
)
from adaptorch.mcp_server import (
    create_mcp_http_app,
    serve_stdio,
)
from adaptorch.providers import DEFAULT_API_KEY_ENV

from adaptorch_mcp.hardening import (
    HardenedMCPServer,
    build_hardened_mcp_server,
    insecure_control_plane_allowed,
    resolve_exposure_profile,
    validate_http_binding,
    validate_separate_tokens,
)

_HOSTED_BASE_URL: Final = "https://adaptorch.com"
_STATUS_PATHS: Final = frozenset({"/mcp/health", "/mcp/metrics"})
MCP_PROVIDER_ENV: Final = "ADAPTORCH_MCP_PROVIDER"
MCP_PROVIDER_MODEL_ENV: Final = "ADAPTORCH_MCP_PROVIDER_MODEL"
MCP_PROVIDER_API_KEY_ENV: Final = "ADAPTORCH_MCP_PROVIDER_API_KEY"
AUTO_PROVIDER: Final = "auto"


def auto_provider_key_envs() -> tuple[str, ...]:
    """The provider key variables ``auto`` inspects, in the order they are reported.

    Derived from the engine's ``DEFAULT_API_KEY_ENV`` so the wrapper can never
    advertise a provider the engine will not execute.
    """
    return tuple(sorted(DEFAULT_API_KEY_ENV.values()))


def _discover_provider_keys(env: Mapping[str, str]) -> list[tuple[str, str]]:
    """``(provider, key_env)`` pairs whose key is set and non-blank, provider-sorted."""
    return [
        (provider, key_env)
        for provider, key_env in sorted(DEFAULT_API_KEY_ENV.items())
        if env.get(key_env, "").strip()
    ]


@dataclass(frozen=True, slots=True)
class ProviderCredentialConfig:
    """Secret-safe wrapper configuration for one process-local provider credential."""

    provider: str
    model: str
    api_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        model = self.model.strip()
        api_key = self.api_key.strip() if self.api_key is not None else None
        if not provider:
            raise ValueError(f"{MCP_PROVIDER_ENV} cannot be empty")
        if not model:
            raise ValueError(f"{MCP_PROVIDER_MODEL_ENV} cannot be empty")
        values = (
            (MCP_PROVIDER_ENV, provider),
            (MCP_PROVIDER_MODEL_ENV, model),
            ("provider key", api_key),
        )
        for label, value in values:
            if value is not None and ("\r" in value or "\n" in value):
                raise ValueError(f"{label} cannot contain newline characters")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "api_key", api_key or None)


def _resolve_auto_credential(
    env: Mapping[str, str],
    *,
    model: str,
    explicit_api_key: str | None,
) -> ProviderCredentialConfig:
    """Pick the one provider whose key is present in *env*; refuse anything else.

    Mirrors the engine's ``ADAPTORCH_EXECUTION_PROVIDER=auto`` rule (exactly one
    key, otherwise unresolved) but reads the tenant's own process environment,
    so the credential that pays for a run is always the tenant's. Messages
    name variables, never values.
    """
    checked = ", ".join(auto_provider_key_envs())
    if explicit_api_key:
        raise ValueError(
            f"{MCP_PROVIDER_ENV}={AUTO_PROVIDER} reads the key from the provider's own "
            f"variable ({checked}); name the provider in {MCP_PROVIDER_ENV} to pass "
            f"{MCP_PROVIDER_API_KEY_ENV} explicitly"
        )
    found = _discover_provider_keys(env)
    if not found:
        raise ValueError(
            f"{MCP_PROVIDER_ENV}={AUTO_PROVIDER} found no provider key; set exactly one "
            f"of {checked}"
        )
    if len(found) > 1:
        present = ", ".join(key_env for _provider, key_env in found)
        raise ValueError(
            f"{MCP_PROVIDER_ENV}={AUTO_PROVIDER} is ambiguous: {present} are all set; "
            f"set {MCP_PROVIDER_ENV} to one provider"
        )
    provider, key_env = found[0]
    return ProviderCredentialConfig(provider=provider, model=model, api_key=env[key_env])


def resolve_provider_credential(
    env: Mapping[str, str],
) -> ProviderCredentialConfig | None:
    provider = env.get(MCP_PROVIDER_ENV, "").strip()
    model = env.get(MCP_PROVIDER_MODEL_ENV, "").strip()
    raw_api_key = env.get(MCP_PROVIDER_API_KEY_ENV)
    api_key = raw_api_key.strip() if raw_api_key is not None else None
    if not provider and not model and not api_key:
        return None
    if not provider or not model:
        raise ValueError(f"{MCP_PROVIDER_ENV} and {MCP_PROVIDER_MODEL_ENV} must be set together")
    if provider.lower() == AUTO_PROVIDER:
        return _resolve_auto_credential(env, model=model, explicit_api_key=api_key or None)
    return ProviderCredentialConfig(provider=provider, model=model, api_key=api_key or None)


def _build_server_for_env(
    *,
    base_url: str,
    api_token: str,
    timeout_seconds: float,
    resolved_env: Mapping[str, str],
) -> HardenedMCPServer:
    common: dict[str, Any] = {
        "base_url": base_url,
        "api_token": api_token,
        "timeout_seconds": timeout_seconds,
        "exposure_profile": resolve_exposure_profile(resolved_env),
        "allow_insecure": insecure_control_plane_allowed(resolved_env),
    }
    provider_credential = resolve_provider_credential(resolved_env)
    if provider_credential is not None:
        common["provider_credential"] = provider_credential
    return build_hardened_mcp_server(**common)


def _required_token(value: str | None, *, label: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def protect_status_endpoints(app: Any, client_token: str) -> Any:
    """Require the client-facing bearer token on health and metrics endpoints."""
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

    expected_token = client_token.strip()

    async def authorize_status(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.url.path not in _STATUS_PATHS:
            return await call_next(request)
        authorization = request.headers.get("authorization")
        if authorization is None:
            return JSONResponse({"detail": "Missing bearer token"}, status_code=401)
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return JSONResponse({"detail": "Invalid authorization header"}, status_code=401)
        if not hmac.compare_digest(token.strip(), expected_token):
            return JSONResponse({"detail": "Invalid bearer token"}, status_code=403)
        return await call_next(request)

    app.middleware("http")(authorize_status)
    return app


def run_hardened_http_server(
    *,
    server: HardenedMCPServer,
    host: str,
    port: int,
    auth_token: str,
) -> int:
    """Run the canonical parent HTTP app with authenticated status endpoints."""
    try:
        import uvicorn
    except ModuleNotFoundError as exc:  # pragma: no cover - optional runtime dependency
        raise ImportError("HTTP transport requires adaptorch[api]") from exc

    app = protect_status_endpoints(
        create_mcp_http_app(server=server, auth_token=auth_token),
        auth_token,
    )
    uvicorn.run(app, host=host, port=port)
    return 0


def run_hardened_main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run stdio or loopback HTTP using the hardened parent facade."""
    resolved_env = os.environ if env is None else env
    parser = build_parent_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    api_token = _required_token(
        args.api_token or resolved_env.get("ADAPTORCH_CONTROL_PLANE_TOKEN"),
        label="upstream control-plane token",
    )
    if args.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    http_auth_token: str | None = None
    if args.transport == "http":
        validate_http_binding(args.http_host)
        if args.http_port < 1 or args.http_port > 65535:
            raise ValueError("http_port must be in range [1, 65535]")
        http_auth_token = _required_token(
            args.http_auth_token or resolved_env.get("ADAPTORCH_MCP_HTTP_AUTH_TOKEN"),
            label="client-facing MCP HTTP token",
        )
        validate_separate_tokens(api_token, http_auth_token)

    server = _build_server_for_env(
        base_url=args.base_url,
        api_token=api_token,
        timeout_seconds=args.timeout_seconds,
        resolved_env=resolved_env,
    )
    if args.transport == "http":
        assert http_auth_token is not None
        return run_hardened_http_server(
            server=server,
            host=args.http_host,
            port=args.http_port,
            auth_token=http_auth_token,
        )
    return serve_stdio(server, framing=args.stdio_framing)


def create_hardened_http_app_from_env(
    env: Mapping[str, str] | None = None,
) -> Any:
    """Build the hardened HTTP app from environment configuration."""
    resolved_env = os.environ if env is None else env
    api_token = _required_token(
        resolved_env.get("ADAPTORCH_CONTROL_PLANE_TOKEN"),
        label="upstream control-plane token",
    )
    http_auth_token = _required_token(
        resolved_env.get("ADAPTORCH_MCP_HTTP_AUTH_TOKEN"),
        label="client-facing MCP HTTP token",
    )
    validate_separate_tokens(api_token, http_auth_token)

    timeout_raw = resolved_env.get("ADAPTORCH_MCP_TIMEOUT_SECONDS", "10.0")
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as exc:
        raise ValueError("ADAPTORCH_MCP_TIMEOUT_SECONDS must be numeric") from exc
    if timeout_seconds <= 0:
        raise ValueError("ADAPTORCH_MCP_TIMEOUT_SECONDS must be > 0")

    server = _build_server_for_env(
        base_url=resolved_env.get("ADAPTORCH_CONTROL_PLANE_BASE_URL", _HOSTED_BASE_URL),
        api_token=api_token,
        timeout_seconds=timeout_seconds,
        resolved_env=resolved_env,
    )
    app = create_mcp_http_app(server=server, auth_token=http_auth_token)
    return protect_status_endpoints(app, http_auth_token)
