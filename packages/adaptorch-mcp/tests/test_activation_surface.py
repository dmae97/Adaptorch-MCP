from __future__ import annotations

import json
import re
import sys
import types
from collections.abc import Sequence
from typing import Any

import pytest

RAW_URL_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*://[^\s]+", re.IGNORECASE)


def _install_fake_adaptorch(monkeypatch: pytest.MonkeyPatch, *, main_return: int = 0) -> list[Any]:
    calls: list[Any] = []
    adaptorch_module = types.ModuleType("adaptorch")
    mcp_server_module = types.ModuleType("adaptorch.mcp_server")

    def fake_main(argv: Sequence[str] | None = None) -> int:
        calls.append(list(argv) if argv is not None else None)
        return main_return

    mcp_server_module.main = fake_main  # type: ignore[attr-defined]
    adaptorch_module.mcp_server = mcp_server_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "adaptorch", adaptorch_module)
    monkeypatch.setitem(sys.modules, "adaptorch.mcp_server", mcp_server_module)
    return calls


def test_cli_does_not_translate_engine_env_vars_into_cli_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_adaptorch(monkeypatch)
    monkeypatch.setenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", "http://env.example.com")
    monkeypatch.setenv("ADAPTORCH_REPRODUCIBLE", "1")
    monkeypatch.setenv("ADAPTORCH_ROUTER_ACCURACY_GATE", "wilson")
    monkeypatch.setenv("ADAPTORCH_PAPER_SEMANTIC_WEIGHT", "0.35")
    monkeypatch.setenv("ADAPTORCH_MCP_MAX_PAYLOAD_SIZE_BYTES", "1048576")

    from adaptorch_mcp.cli import main

    result = main(["--transport", "stdio"])

    assert result == 0
    assert calls == [["--base-url", "http://env.example.com", "--transport", "stdio"]]


def test_diagnostics_surfaces_allowed_origins() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics, format_diagnostics

    payload = collect_diagnostics(
        {
            "ADAPTORCH_MCP_ALLOWED_ORIGINS": "http://127.0.0.1:8765",
            "ADAPTORCH_CONTROL_PLANE_TOKEN": "secret-token-value",
        }
    )
    rendered = json.dumps(payload) + "\n" + format_diagnostics(payload)

    assert payload["environment"]["config"]["ADAPTORCH_MCP_ALLOWED_ORIGINS"] == (
        "http://127.0.0.1:8765"
    )
    assert "ADAPTORCH_MCP_ALLOWED_ORIGINS" in rendered
    assert "secret-token-value" not in rendered


def test_control_plane_env_error_never_contains_raw_url() -> None:
    from adaptorch_mcp.diagnostics import collect_diagnostics

    raw_url = "ftp://raw.example.com/private-path"
    payload = collect_diagnostics({"ADAPTORCH_CONTROL_PLANE_BASE_URL": raw_url})
    control_plane = payload["controlPlane"]
    env_error = str(control_plane["envError"])

    assert control_plane["invalidEnvUrl"] is True
    assert env_error
    assert raw_url not in env_error
    assert RAW_URL_PATTERN.search(env_error) is None
