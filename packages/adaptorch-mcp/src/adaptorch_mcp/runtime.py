from __future__ import annotations

import hmac
import os
from collections.abc import Mapping, Sequence
from typing import Any, Final

from adaptorch.mcp_server import (
    build_parser as build_parent_parser,
)
from adaptorch.mcp_server import (
    create_mcp_http_app,
    serve_stdio,
)

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

    server = build_hardened_mcp_server(
        base_url=args.base_url,
        api_token=api_token,
        timeout_seconds=args.timeout_seconds,
        exposure_profile=resolve_exposure_profile(resolved_env),
        allow_insecure=insecure_control_plane_allowed(resolved_env),
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

    server = build_hardened_mcp_server(
        base_url=resolved_env.get("ADAPTORCH_CONTROL_PLANE_BASE_URL", _HOSTED_BASE_URL),
        api_token=api_token,
        timeout_seconds=timeout_seconds,
        exposure_profile=resolve_exposure_profile(resolved_env),
        allow_insecure=insecure_control_plane_allowed(resolved_env),
    )
    app = create_mcp_http_app(server=server, auth_token=http_auth_token)
    return protect_status_endpoints(app, http_auth_token)
