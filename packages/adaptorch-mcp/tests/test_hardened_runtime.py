from __future__ import annotations

from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse

from adaptorch_mcp import runtime


def test_stdio_runtime_builds_remote_profile_and_serves(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    fake_server = object()

    def fake_build(**kwargs: Any) -> object:
        calls.append(("build", kwargs))
        return fake_server

    def fake_serve(server: object, *, framing: str) -> int:
        calls.append(("serve", (server, framing)))
        return 7

    monkeypatch.setattr(runtime, "build_hardened_mcp_server", fake_build)
    monkeypatch.setattr(runtime, "serve_stdio", fake_serve)

    result = runtime.run_hardened_main(
        ["--transport", "stdio", "--base-url", "https://adaptorch.com"],
        env={"ADAPTORCH_CONTROL_PLANE_TOKEN": "upstream-token"},
    )

    assert result == 7
    assert calls[0] == (
        "build",
        {
            "base_url": "https://adaptorch.com",
            "api_token": "upstream-token",
            "timeout_seconds": 10.0,
            "exposure_profile": "remote",
            "allow_insecure": False,
        },
    )
    assert calls[1] == ("serve", (fake_server, "newline"))


def test_http_runtime_requires_distinct_token_and_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "build_hardened_mcp_server", lambda **_kwargs: object())
    monkeypatch.setattr(runtime, "run_hardened_http_server", lambda **_kwargs: 9)

    with pytest.raises(ValueError, match="differ"):
        runtime.run_hardened_main(
            ["--transport", "http", "--base-url", "https://adaptorch.com"],
            env={
                "ADAPTORCH_CONTROL_PLANE_TOKEN": "same-token",
                "ADAPTORCH_MCP_HTTP_AUTH_TOKEN": " same-token ",
            },
        )

    with pytest.raises(ValueError, match="loopback"):
        runtime.run_hardened_main(
            [
                "--transport",
                "http",
                "--base-url",
                "https://adaptorch.com",
                "--http-host",
                "0.0.0.0",
            ],
            env={
                "ADAPTORCH_CONTROL_PLANE_TOKEN": "upstream-token",
                "ADAPTORCH_MCP_HTTP_AUTH_TOKEN": "client-token",
            },
        )

    assert (
        runtime.run_hardened_main(
            ["--transport", "http", "--base-url", "https://adaptorch.com"],
            env={
                "ADAPTORCH_CONTROL_PLANE_TOKEN": "upstream-token",
                "ADAPTORCH_MCP_HTTP_AUTH_TOKEN": "client-token",
            },
        )
        == 9
    )


def test_runtime_rejects_remote_plaintext_unless_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "serve_stdio", lambda *_args, **_kwargs: 0)

    with pytest.raises(ValueError, match="remote HTTP"):
        runtime.run_hardened_main(
            ["--transport", "stdio", "--base-url", "http://dev.example.com"],
            env={"ADAPTORCH_CONTROL_PLANE_TOKEN": "upstream-token"},
        )

    built: list[str] = []

    def fake_build(**kwargs: Any) -> object:
        built.append(kwargs["base_url"])
        return object()

    monkeypatch.setattr(runtime, "build_hardened_mcp_server", fake_build)
    assert (
        runtime.run_hardened_main(
            ["--transport", "stdio", "--base-url", "http://dev.example.com"],
            env={
                "ADAPTORCH_CONTROL_PLANE_TOKEN": "upstream-token",
                "ADAPTORCH_MCP_ALLOW_INSECURE_CONTROL_PLANE": "1",
            },
        )
        == 0
    )
    assert built == ["http://dev.example.com"]


def test_default_http_factory_uses_hardened_server_and_distinct_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_server = object()
    fake_app = object()
    calls: list[tuple[str, Any]] = []

    def fake_build(**kwargs: Any) -> object:
        calls.append(("build", kwargs))
        return fake_server

    def fake_create(*, server: object, auth_token: str) -> object:
        calls.append(("app", (server, auth_token)))
        return fake_app

    monkeypatch.setattr(runtime, "build_hardened_mcp_server", fake_build)
    monkeypatch.setattr(runtime, "create_mcp_http_app", fake_create)
    monkeypatch.setattr(runtime, "protect_status_endpoints", lambda app, _token: app)

    app = runtime.create_hardened_http_app_from_env(
        {
            "ADAPTORCH_CONTROL_PLANE_BASE_URL": "https://adaptorch.com",
            "ADAPTORCH_CONTROL_PLANE_TOKEN": "upstream-token",
            "ADAPTORCH_MCP_HTTP_AUTH_TOKEN": "client-token",
        }
    )

    assert app is fake_app
    assert calls[0][0] == "build"
    assert calls[1] == ("app", (fake_server, "client-token"))


def test_public_cli_delegates_to_hardened_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from adaptorch_mcp import cli

    calls: list[list[str] | None] = []

    def fake_main(argv: list[str] | None = None) -> int:
        calls.append(argv)
        return 11

    monkeypatch.setattr(cli, "_load_runtime_main", lambda: fake_main)
    monkeypatch.delenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", raising=False)

    assert cli.main(["--transport", "stdio"]) == 11
    assert calls == [["--base-url", "https://adaptorch.com", "--transport", "stdio"]]


def test_public_http_factory_delegates_to_hardened_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adaptorch_mcp import server

    fake_app = object()
    monkeypatch.setattr(server, "_load_runtime_app_factory", lambda: lambda: fake_app)

    assert server.create_default_mcp_http_app() is fake_app


def test_status_endpoints_require_the_client_bearer_token() -> None:
    app = runtime.protect_status_endpoints(FastAPI(), "client-token")
    dispatch = app.user_middleware[0].kwargs["dispatch"]

    def request_with_token(token: str | None) -> Request:
        headers = [] if token is None else [(b"authorization", f"Bearer {token}".encode())]
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/mcp/health",
                "raw_path": b"/mcp/health",
                "query_string": b"",
                "headers": headers,
                "client": ("127.0.0.1", 1234),
                "server": ("127.0.0.1", 8765),
                "root_path": "",
            }
        )

    async def exercise() -> None:
        async def call_next(_request: Request) -> JSONResponse:
            return JSONResponse({"status": "ok"})

        missing = await dispatch(request_with_token(None), call_next)
        wrong = await dispatch(request_with_token("wrong-token"), call_next)
        valid = await dispatch(request_with_token("client-token"), call_next)
        assert missing.status_code == 401
        assert wrong.status_code == 403
        assert valid.status_code == 200

    anyio.run(exercise)
