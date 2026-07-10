from __future__ import annotations

import sys
from collections.abc import Sequence

import pytest

RuntimeCall = list[str] | None | str


def _install_fake_adaptorch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    main_return: int = 0,
) -> list[RuntimeCall]:
    from adaptorch_mcp import cli, server

    calls: list[RuntimeCall] = []

    def fake_main(argv: Sequence[str] | None = None) -> int:
        calls.append(list(argv) if argv is not None else None)
        return main_return

    def fake_app_factory() -> dict[str, str]:
        calls.append("create_default_mcp_http_app")
        return {"app": "fake"}

    monkeypatch.setattr(cli, "_load_runtime_main", lambda: fake_main)
    monkeypatch.setattr(server, "_load_runtime_app_factory", lambda: fake_app_factory)
    return calls


def test_cli_delegates_to_adaptorch_mcp_main(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch, main_return=17)

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio", "--base-url", "http://127.0.0.1:8000"])

    assert result == 17
    assert calls == [["--transport", "stdio", "--base-url", "http://127.0.0.1:8000"]]


def test_cli_defaults_to_hosted_control_plane(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.delenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", raising=False)

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio"])

    assert result == 0
    assert calls == [["--base-url", "https://adaptorch.com", "--transport", "stdio"]]


def test_cli_forwards_env_base_url_when_no_explicit_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.setenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", "http://env.example.com")

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio"])

    assert result == 0
    assert calls == [["--base-url", "http://env.example.com", "--transport", "stdio"]]


def test_cli_explicit_base_url_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.setenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", "http://env.example.com")

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio", "--base-url", "http://explicit.example.com"])

    assert result == 0
    assert calls == [["--transport", "stdio", "--base-url", "http://explicit.example.com"]]


def test_cli_base_url_equals_form_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.setenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", "http://env.example.com")

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio", "--base-url=http://explicit.example.com"])

    assert result == 0
    assert calls == [["--transport", "stdio", "--base-url=http://explicit.example.com"]]


def test_cli_whitespace_only_env_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.setenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", "   \t  ")

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio"])

    assert result == 0
    assert calls == [["--base-url", "https://adaptorch.com", "--transport", "stdio"]]


def test_cli_strips_valid_env_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.setenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", "  http://env.example.com  ")

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio"])

    assert result == 0
    assert calls == [["--base-url", "http://env.example.com", "--transport", "stdio"]]


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-valid-url",
        "http://",
        "://no-host",
        "ftp://example.com",
        "https://user:pass@example.com",
    ],
)
def test_cli_invalid_env_base_url_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
    bad: str,
) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.setenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", bad)

    from adaptorch_mcp.cli import main

    with pytest.raises(ValueError, match="ADAPTORCH_CONTROL_PLANE_BASE_URL"):
        main(["--transport", "stdio"])
    assert calls == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--transport", "stdio", "--base-url", "ftp://example.com"],
        ["--transport", "stdio", "--base-url=http://"],
        ["--transport", "stdio", "--base-url", "https://user:pass@example.com"],
    ],
)
def test_cli_invalid_explicit_base_url_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.setenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", "http://env.example.com")

    from adaptorch_mcp.cli import main

    with pytest.raises(ValueError, match="--base-url"):
        main(argv)
    assert calls == []


def test_cli_missing_adaptorch_dependency_returns_helpful_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from adaptorch_mcp import cli

    def missing_runtime() -> None:
        raise ModuleNotFoundError("No module named 'adaptorch'", name="adaptorch")

    monkeypatch.setattr(cli, "_load_runtime_main", missing_runtime)

    assert cli.main(["--transport", "stdio"]) == 2
    assert "adaptorch-mcp requires AdaptOrch" in capsys.readouterr().err


def test_cli_empty_equals_base_url_falls_through_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.setenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", "http://env.example.com")

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio", "--base-url="])

    assert result == 0
    assert calls == [["--base-url", "http://env.example.com", "--transport", "stdio"]]


def test_cli_empty_equals_base_url_falls_through_to_hosted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.delenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", raising=False)

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio", "--base-url="])

    assert result == 0
    assert calls == [["--base-url", "https://adaptorch.com", "--transport", "stdio"]]


def test_cli_argv_none_uses_sys_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["adaptorch-mcp", "--transport", "stdio"])

    from adaptorch_mcp.cli import _with_hosted_base_url_default

    assert _with_hosted_base_url_default(None) == [
        "--base-url",
        "https://adaptorch.com",
        "--transport",
        "stdio",
    ]


def test_cli_argv_none_with_explicit_flag_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["adaptorch-mcp", "--base-url", "http://x", "--transport", "stdio"],
    )

    from adaptorch_mcp.cli import _with_hosted_base_url_default

    assert _with_hosted_base_url_default(None) is None


def test_stdio_smoke_base_url_default_is_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", raising=False)

    from adaptorch_mcp.stdio_smoke import build_parser

    args = build_parser().parse_args([])

    assert args.base_url == "http://127.0.0.1:8000"


def test_server_factory_delegates_to_adaptorch_http_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch)

    from adaptorch_mcp.server import create_default_mcp_http_app

    assert create_default_mcp_http_app() == {"app": "fake"}
    assert calls == ["create_default_mcp_http_app"]


def test_package_exports_public_contract() -> None:
    import adaptorch_mcp

    assert adaptorch_mcp.__version__ == "0.4.0"
    assert callable(adaptorch_mcp.main)
    assert callable(adaptorch_mcp.collect_diagnostics)
    assert callable(adaptorch_mcp.create_default_mcp_http_app)
