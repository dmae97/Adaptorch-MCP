from __future__ import annotations

import json
import sys
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _install_fake_adaptorch(monkeypatch: pytest.MonkeyPatch, *, main_return: int = 0) -> list[Any]:
    calls: list[Any] = []
    adaptorch_module = types.ModuleType("adaptorch")
    mcp_server_module = types.ModuleType("adaptorch.mcp_server")

    def fake_main(argv: Sequence[str] | None = None) -> int:
        calls.append(list(argv) if argv is not None else None)
        return main_return

    def fake_app_factory() -> dict[str, str]:
        calls.append("create_default_mcp_http_app")
        return {"app": "fake"}

    mcp_server_module.main = fake_main  # type: ignore[attr-defined]
    mcp_server_module.create_default_mcp_http_app = fake_app_factory  # type: ignore[attr-defined]
    adaptorch_module.mcp_server = mcp_server_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "adaptorch", adaptorch_module)
    monkeypatch.setitem(sys.modules, "adaptorch.mcp_server", mcp_server_module)
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
    assert calls == [["--base-url", "https://adaptorch.ai.kr", "--transport", "stdio"]]


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
    assert calls == [["--base-url", "https://adaptorch.ai.kr", "--transport", "stdio"]]


def test_cli_strips_valid_env_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.setenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", "  http://env.example.com  ")

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio"])

    assert result == 0
    assert calls == [["--base-url", "http://env.example.com", "--transport", "stdio"]]


@pytest.mark.parametrize("bad", ["not-a-valid-url", "http://", "://no-host", "ftp://example.com"])
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
    assert calls == [["--base-url", "https://adaptorch.ai.kr", "--transport", "stdio"]]


def test_cli_argv_none_uses_sys_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["adaptorch-mcp", "--transport", "stdio"])

    from adaptorch_mcp.cli import _with_hosted_base_url_default

    assert _with_hosted_base_url_default(None) == [
        "--base-url",
        "https://adaptorch.ai.kr",
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

    assert adaptorch_mcp.__version__ == "0.2.0"
    assert callable(adaptorch_mcp.main)
    assert callable(adaptorch_mcp.collect_diagnostics)
    assert callable(adaptorch_mcp.create_default_mcp_http_app)


def test_diagnostics_redacts_token_values() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics, format_diagnostics

    payload = collect_diagnostics(
        {
            "ADAPTORCH_CONTROL_PLANE_TOKEN": "secret-token-value",
            "ADAPTORCH_CONTROL_PLANE_BASE_URL": "https://adaptorch.ai.kr",
        }
    )
    rendered = json.dumps(payload) + "\n" + format_diagnostics(payload)

    assert "secret-token-value" not in rendered
    token_status = payload["environment"]["tokens"]["ADAPTORCH_CONTROL_PLANE_TOKEN"]
    assert token_status == {"set": True, "length": len("secret-token-value")}
    assert "adaptorch_plan_catalog" in payload["expectedTools"]
    assert "adaptorch_cancel_run" in payload["expectedTools"]


def test_diagnostics_reports_control_plane_for_valid_env() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics, format_diagnostics

    payload = collect_diagnostics(
        {
            "ADAPTORCH_CONTROL_PLANE_BASE_URL": "  http://env.example.com  ",
            "ADAPTORCH_CONTROL_PLANE_TOKEN": "secret-token-value",
        }
    )

    control_plane = payload["controlPlane"]
    assert control_plane["defaultBaseUrl"] == "https://adaptorch.ai.kr"
    assert control_plane["envBaseUrl"] == "http://env.example.com"
    assert control_plane["resolvedBaseUrl"] == "http://env.example.com"
    assert control_plane["resolvedSource"] == "env"
    assert control_plane["invalidEnvUrl"] is False
    rendered = json.dumps(payload) + "\n" + format_diagnostics(payload)
    assert "secret-token-value" not in rendered


def test_diagnostics_reports_control_plane_hosted_when_env_unset_or_whitespace() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics

    for env in (None, {"ADAPTORCH_CONTROL_PLANE_BASE_URL": "   "}):
        payload = collect_diagnostics(env)
        control_plane = payload["controlPlane"]
        assert control_plane["resolvedBaseUrl"] == "https://adaptorch.ai.kr"
        assert control_plane["resolvedSource"] == "hosted-default"
        assert control_plane["envBaseUrl"] is None
        assert control_plane["invalidEnvUrl"] is False


def test_diagnostics_flags_invalid_env_url_without_raising() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics

    payload = collect_diagnostics({"ADAPTORCH_CONTROL_PLANE_BASE_URL": "not-a-valid-url"})
    control_plane = payload["controlPlane"]

    assert control_plane["invalidEnvUrl"] is True
    assert control_plane["resolvedBaseUrl"] == "https://adaptorch.ai.kr"
    assert control_plane["resolvedSource"] == "hosted-default"


def test_diagnostics_redacts_base_url_userinfo() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics, format_diagnostics

    payload = collect_diagnostics(
        {"ADAPTORCH_CONTROL_PLANE_BASE_URL": "https://user:pass@example.com/path"}
    )
    rendered = json.dumps(payload) + "\n" + format_diagnostics(payload)

    assert "user:pass" not in rendered
    assert payload["controlPlane"]["envBaseUrl"] == "https://example.com/path"


def test_stdio_smoke_accepts_expected_tools(tmp_path: Path) -> None:
    from adaptorch_mcp.stdio_smoke import run_stdio_smoke

    fake_server = tmp_path / "fake_mcp_server.py"
    fake_server.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg['method'] == 'initialize':\n"
        "        result = {'protocolVersion': msg['params']['protocolVersion']}\n"
        "    else:\n"
        "        tools = [{'name': 'adaptorch_run'}, {'name': 'adaptorch_plan_catalog'}]\n"
        "        result = {'tools': tools}\n"
        "    response = {'jsonrpc': '2.0', 'id': msg['id'], 'result': result}\n"
        "    print(json.dumps(response), flush=True)\n",
        encoding="utf-8",
    )

    payload = run_stdio_smoke(
        [sys.executable, str(fake_server)],
        expected_tools=("adaptorch_run", "adaptorch_plan_catalog"),
        timeout_seconds=2,
    )

    assert payload["ok"] is True
    assert payload["tool_count"] == 2
    assert payload["protocolVersion"] == "2024-11-05"


def test_stdio_smoke_reports_missing_tool(tmp_path: Path) -> None:
    from adaptorch_mcp.stdio_smoke import MCPStdioSmokeError, run_stdio_smoke

    fake_server = tmp_path / "fake_mcp_server.py"
    fake_server.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg['method'] == 'initialize':\n"
        "        result = {'protocolVersion': '2024-11-05'}\n"
        "    else:\n"
        "        result = {'tools': []}\n"
        "    response = {'jsonrpc': '2.0', 'id': msg['id'], 'result': result}\n"
        "    print(json.dumps(response), flush=True)\n",
        encoding="utf-8",
    )

    with pytest.raises(MCPStdioSmokeError, match="missing expected tools"):
        run_stdio_smoke(
            [sys.executable, str(fake_server)],
            expected_tools=("adaptorch_run",),
            timeout_seconds=2,
        )
