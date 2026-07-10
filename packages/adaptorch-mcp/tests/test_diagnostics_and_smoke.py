from __future__ import annotations

import json
import runpy
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

RuntimeCall = list[str] | None | str


def _install_fake_adaptorch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    main_return: int = 0,
) -> list[RuntimeCall]:
    from adaptorch_mcp import cli

    calls: list[RuntimeCall] = []

    def fake_main(argv: Sequence[str] | None = None) -> int:
        calls.append(list(argv) if argv is not None else None)
        return main_return

    monkeypatch.setattr(cli, "_load_runtime_main", lambda: fake_main)
    return calls


def test_diagnostics_redacts_token_values() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics, format_diagnostics

    payload = collect_diagnostics(
        {
            "ADAPTORCH_CONTROL_PLANE_TOKEN": "secret-token-value",
            "ADAPTORCH_CONTROL_PLANE_BASE_URL": "https://adaptorch.com",
        }
    )
    rendered = json.dumps(payload) + "\n" + format_diagnostics(payload)

    assert "secret-token-value" not in rendered
    token_status = payload["environment"]["tokens"]["ADAPTORCH_CONTROL_PLANE_TOKEN"]
    assert token_status == {"set": True, "formatRecognized": False}
    assert "adaptorch_plan_catalog" in payload["expectedTools"]
    assert "adaptorch_cancel_run" in payload["expectedTools"]


def test_diagnostics_reports_control_plane_for_valid_env() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics, format_diagnostics

    payload = collect_diagnostics(
        {
            "ADAPTORCH_CONTROL_PLANE_BASE_URL": "  http://env.example.com  ",
            "ADAPTORCH_CONTROL_PLANE_TOKEN": "secret-token-value",
            "ADAPTORCH_MCP_ALLOW_INSECURE_CONTROL_PLANE": "1",
        }
    )

    control_plane = payload["controlPlane"]
    assert control_plane["defaultBaseUrl"] == "https://adaptorch.com"
    assert control_plane["envBaseUrl"] == "http://env.example.com"
    assert control_plane["resolvedBaseUrl"] == "http://env.example.com"
    assert control_plane["resolvedSource"] == "env"
    assert control_plane["invalidEnvUrl"] is False
    assert control_plane["policyValid"] is True
    assert payload["security"]["remoteControlPlaneRequiresHttps"] is False
    assert payload["ok"] is True
    rendered = json.dumps(payload) + "\n" + format_diagnostics(payload)
    assert "secret-token-value" not in rendered


def test_diagnostics_reports_control_plane_hosted_when_env_unset_or_whitespace() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics

    for env in (None, {"ADAPTORCH_CONTROL_PLANE_BASE_URL": "   "}):
        payload = collect_diagnostics(env)
        control_plane = payload["controlPlane"]
        assert control_plane["resolvedBaseUrl"] == "https://adaptorch.com"
        assert control_plane["resolvedSource"] == "hosted-default"
        assert control_plane["envBaseUrl"] is None
        assert control_plane["invalidEnvUrl"] is False


def test_diagnostics_flags_invalid_env_url_without_raising() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics

    payload = collect_diagnostics({"ADAPTORCH_CONTROL_PLANE_BASE_URL": "not-a-valid-url"})
    control_plane = payload["controlPlane"]

    assert control_plane["invalidEnvUrl"] is True
    assert control_plane["resolvedBaseUrl"] == "https://adaptorch.com"
    assert control_plane["resolvedSource"] == "hosted-default"


def test_diagnostics_redacts_base_url_userinfo() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics, format_diagnostics

    payload = collect_diagnostics(
        {"ADAPTORCH_CONTROL_PLANE_BASE_URL": "https://user:pass@example.com/path"}
    )
    rendered = json.dumps(payload) + "\n" + format_diagnostics(payload)

    assert "user:pass" not in rendered
    assert payload["controlPlane"]["envBaseUrl"] is None
    assert payload["controlPlane"]["invalidEnvUrl"] is True


def test_expected_core_tools_are_canonical() -> None:
    from adaptorch_mcp.diagnostics import EXPECTED_CORE_TOOLS

    assert EXPECTED_CORE_TOOLS == (
        "adaptorch_run",
        "adaptorch_get_run",
        "adaptorch_get_artifacts",
        "adaptorch_list_runs",
        "adaptorch_cancel_run",
        "adaptorch_server_metrics",
        "adaptorch_capabilities",
        "adaptorch_plan_catalog",
    )


def test_pyproject_registers_console_scripts() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"] == {
        "adaptorch-mcp": "adaptorch_mcp.cli:main",
        "adaptorch-mcp-doctor": "adaptorch_mcp.doctor:main",
        "adaptorch-mcp-smoke": "adaptorch_mcp.stdio_smoke:main",
    }


def test_doctor_json_and_strict_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from adaptorch_mcp import doctor

    payload = {
        "ok": True,
        "environment": {
            "tokens": {"ADAPTORCH_CONTROL_PLANE_TOKEN": {"set": False, "length": None}},
        },
    }
    monkeypatch.setattr(doctor, "collect_diagnostics", lambda: payload)

    assert doctor.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert doctor.main(["--strict"]) == 1


def test_module_entrypoint_delegates_to_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.delenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["adaptorch-mcp", "--transport", "stdio"])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("adaptorch_mcp.__main__", run_name="__main__")

    assert excinfo.value.code == 0
    assert calls == [["--base-url", "https://adaptorch.com", "--transport", "stdio"]]


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


def test_stdio_smoke_redacts_sensitive_stderr(tmp_path: Path) -> None:
    from adaptorch_mcp.stdio_smoke import MCPStdioSmokeError, run_stdio_smoke

    fake_server = tmp_path / "leaky_stderr_server.py"
    fake_server.write_text(
        "import os, sys\n"
        "print(os.environ['ADAPTORCH_CONTROL_PLANE_TOKEN'], file=sys.stderr, flush=True)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    token = "fake-sensitive-token-12345"

    with pytest.raises(MCPStdioSmokeError) as excinfo:
        run_stdio_smoke(
            [sys.executable, str(fake_server)],
            env={"ADAPTORCH_CONTROL_PLANE_TOKEN": token},
            timeout_seconds=2,
        )

    message = str(excinfo.value)
    assert token not in message
    assert "[redacted]" in message


def test_stdio_smoke_redacts_jsonrpc_error_payload(tmp_path: Path) -> None:
    from adaptorch_mcp.stdio_smoke import MCPStdioSmokeError, run_stdio_smoke

    fake_server = tmp_path / "leaky_error_server.py"
    fake_server.write_text(
        "import json, os, sys\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    response = {\n"
        "        'jsonrpc': '2.0',\n"
        "        'id': msg['id'],\n"
        "        'error': {'message': os.environ['ADAPTORCH_CONTROL_PLANE_TOKEN']},\n"
        "    }\n"
        "    print(json.dumps(response), flush=True)\n",
        encoding="utf-8",
    )
    token = "fake-jsonrpc-token-12345"

    with pytest.raises(MCPStdioSmokeError) as excinfo:
        run_stdio_smoke(
            [sys.executable, str(fake_server)],
            env={"ADAPTORCH_CONTROL_PLANE_TOKEN": token},
            timeout_seconds=2,
        )

    message = str(excinfo.value)
    assert token not in message
    assert "[redacted]" in message


def test_stdio_smoke_main_redacts_failure_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from adaptorch_mcp.stdio_smoke import main

    fake_server = tmp_path / "leaky_main_server.py"
    fake_server.write_text(
        "import os, sys\n"
        "print(os.environ['ADAPTORCH_CONTROL_PLANE_TOKEN'], file=sys.stderr, flush=True)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    token = "fake-main-token-12345"

    result = main(
        [
            "--command",
            f"{sys.executable} {fake_server}",
            "--api-token",
            token,
            "--timeout-seconds",
            "2",
        ]
    )

    assert result == 1
    rendered = capsys.readouterr().out
    assert token not in rendered
    assert "[redacted]" in rendered
