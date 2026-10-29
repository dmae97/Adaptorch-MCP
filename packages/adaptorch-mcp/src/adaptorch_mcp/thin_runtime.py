"""Public CLI and ASGI factory for the remote-only MCP client."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from collections.abc import Mapping, Sequence

from adaptorch_client.provider import ProviderCredential
from adaptorch_mcp.security_policy import validate_http_binding, validate_separate_tokens
from adaptorch_mcp.thin_remote import RemoteMCPServer

_HOSTED_URL = "https://adaptorch.com"
_PROVIDER_KEY_ENVS = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "opencode_go": "OPENCODE_GO_API_KEY",
    "openai_codex": "OPENAI_CODEX_API_KEY",
    "workbuddy": "WORKBUDDY_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "commandcode": "COMMANDCODE_API_KEY",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adaptorch-mcp", description="Remote AdaptOrch MCP client"
    )
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--base-url", default=_HOSTED_URL)
    parser.add_argument("--api-token")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--http-auth-token")
    parser.add_argument("--stdio-framing", choices=["newline", "content-length"], default="newline")
    return parser


def provider_credential_from_env(env: Mapping[str, str]) -> ProviderCredential | None:
    provider = env.get("ADAPTORCH_MCP_PROVIDER", "").strip()
    model = env.get("ADAPTORCH_MCP_PROVIDER_MODEL", "").strip()
    key = env.get("ADAPTORCH_MCP_PROVIDER_API_KEY", "").strip()
    command = env.get("ADAPTORCH_MCP_PROVIDER_API_KEY_COMMAND", "").strip()
    auth_type = env.get("ADAPTORCH_MCP_PROVIDER_AUTH_TYPE", "").strip() or None
    account_id = env.get("ADAPTORCH_MCP_PROVIDER_ACCOUNT_ID", "").strip() or None
    if not any((provider, model, key, command, auth_type, account_id)):
        return None
    if not provider or not model:
        raise ValueError("MCP provider and model must be set together")
    if any(
        env.get(name, "").strip()
        for name in (
            "ADAPTORCH_MCP_PROVIDER_FALLBACK",
            "ADAPTORCH_MCP_PROVIDER_FALLBACK_API_KEY",
        )
    ):
        raise ValueError("provider fallback is not supported by the remote-only client")
    if key and command:
        raise ValueError("provider API key and key command are mutually exclusive")
    if provider == "auto":
        if key or command or auth_type or account_id:
            raise ValueError("auto provider reads exactly one provider-specific key")
        found = [
            (name, variable) for name, variable in _PROVIDER_KEY_ENVS.items() if env.get(variable)
        ]
        if len(found) != 1:
            raise ValueError("auto provider requires exactly one provider-specific key")
        provider, variable = found[0]
        key = env[variable]
    if command:
        argv = shlex.split(command)
        if not argv:
            raise ValueError("provider key command cannot be empty")
        try:
            completed = subprocess.run(
                argv, capture_output=True, text=True, timeout=15, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("provider key command failed") from exc
        if completed.returncode != 0:
            raise ValueError("provider key command failed")
        key = completed.stdout.strip()
    if not key or "\n" in key or "\r" in key:
        raise ValueError("provider credential must be one non-empty line")
    return ProviderCredential(provider, model, key, auth_type=auth_type, account_id=account_id)


def run_remote_main(
    argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None
) -> int:
    resolved = os.environ if env is None else env
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    token = (args.api_token or resolved.get("ADAPTORCH_CONTROL_PLANE_TOKEN", "")).strip()
    if not token and args.transport == "stdio":
        # Registry introspection: list tools locally; calls fail closed without a token.
        from adaptorch_mcp.thin_stdio import serve_stdio

        return serve_stdio(RemoteMCPServer.discovery_only(), framing=args.stdio_framing)
    if not token:
        raise ValueError("ADAPTORCH_CONTROL_PLANE_TOKEN is required")
    server = RemoteMCPServer.from_config(
        base_url=args.base_url,
        api_token=token,
        timeout_seconds=args.timeout_seconds,
        provider_credential=provider_credential_from_env(resolved),
    )
    if args.transport == "http":
        client_token = (
            args.http_auth_token or resolved.get("ADAPTORCH_MCP_HTTP_AUTH_TOKEN", "")
        ).strip()
        validate_http_binding(args.http_host)
        validate_separate_tokens(token, client_token)
        if not 1 <= args.http_port <= 65535:
            raise ValueError("http_port must be in range [1, 65535]")
        import uvicorn

        from adaptorch_mcp.thin_http import create_remote_http_app

        uvicorn.run(
            create_remote_http_app(server=server, auth_token=client_token),
            host=args.http_host,
            port=args.http_port,
            server_header=False,
            limit_concurrency=128,
            timeout_graceful_shutdown=10,
        )
        return 0
    from adaptorch_mcp.thin_stdio import serve_stdio

    return serve_stdio(server, framing=args.stdio_framing)


def create_remote_http_app_from_env(env: Mapping[str, str] | None = None) -> object:
    resolved = os.environ if env is None else env
    token = resolved.get("ADAPTORCH_CONTROL_PLANE_TOKEN", "").strip()
    client_token = resolved.get("ADAPTORCH_MCP_HTTP_AUTH_TOKEN", "").strip()
    validate_separate_tokens(token, client_token)
    server = RemoteMCPServer.from_config(
        base_url=resolved.get("ADAPTORCH_CONTROL_PLANE_BASE_URL", _HOSTED_URL),
        api_token=token,
        timeout_seconds=float(resolved.get("ADAPTORCH_MCP_TIMEOUT_SECONDS", "10.0")),
        provider_credential=provider_credential_from_env(resolved),
    )
    from adaptorch_mcp.thin_http import create_remote_http_app

    return create_remote_http_app(server=server, auth_token=client_token)
