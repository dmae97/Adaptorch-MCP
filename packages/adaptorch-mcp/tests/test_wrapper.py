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


def test_server_factory_delegates_to_adaptorch_http_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch)

    from adaptorch_mcp.server import create_default_mcp_http_app

    assert create_default_mcp_http_app() == {"app": "fake"}
    assert calls == ["create_default_mcp_http_app"]


def test_package_exports_public_contract() -> None:
    import adaptorch_mcp

    assert adaptorch_mcp.__version__ == "0.1.0"
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
