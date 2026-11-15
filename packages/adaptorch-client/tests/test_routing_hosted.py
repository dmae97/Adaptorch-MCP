"""The actual CLI, SDK and thin MCP reach one authenticated engine, without providers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_hosted_wiring import HostedFixture
from test_hosted_wiring import hosted as hosted

from adaptorch_client import JSONMapping


def test_cli_sdk_and_mcp_share_real_pesco_route(hosted: HostedFixture, tmp_path: Path) -> None:
    remote = pytest.importorskip("adaptorch_mcp.thin_remote")
    arguments: JSONMapping = {
        "subtasks": [
            {"id": "a", "description": "inspect"},
            {"id": "b", "description": "verify"},
        ],
        "dependencies": [{"from": "a", "to": "b"}],
        "prefer_ensemble_singleton": False,
    }
    expected = hosted.client.route_topology(arguments).to_payload()
    assert expected["topology"] == "sequential"
    pesco = expected["pesco"]
    assert isinstance(pesco, dict) and pesco["execution_authorized"] is False
    root = Path(__file__).resolve().parents[3]
    env = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "PYTHONPATH": os.pathsep.join(
            str(root / "packages" / name / "src")
            for name in (
                "adaptorch-cli",
                "adaptorch-client",
                "adaptorch-mcp",
            )
        ),
        "ADAPTORCH_API_KEY": hosted.api_key,
    }
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "adaptorch_cli",
            "--api-url",
            hosted.wire.api_url,
            "route",
            "--file",
            "-",
        ],
        input=json.dumps(arguments),
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == expected
    server = remote.RemoteMCPServer.from_config(
        base_url=hosted.wire.api_url,
        api_token=hosted.api_key,
        timeout_seconds=10,
    )
    try:
        message = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "adaptorch_route_topology",
                "arguments": arguments,
            },
        }
        response = server.handle_message(message)
        assert not response["result"].get("isError"), response
        assert json.loads(response["result"]["content"][0]["text"]) == expected
        rejected = server.handle_message(
            {
                **message,
                "params": {
                    "name": "adaptorch_route_topology",
                    "arguments": {**arguments, "pesco_policy": {"qualified": True}},
                },
            }
        )
        assert rejected["error"]["code"] == -32602
        denied = remote.RemoteMCPServer.discovery_only().handle_message(message)
        assert denied["error"]["code"] == -32001
    finally:
        server.close()
    assert hosted.client.list_runs().items == ()
    assert all(
        not any(k.lower().startswith("x-provider") for k in r.headers) for r in hosted.wire.requests
    )
    assert hosted.api_key not in process.stdout + process.stderr


def test_optional_route_contract_matches_current_engine() -> None:
    engine = pytest.importorskip("adaptorch.mcp_server")
    remote = pytest.importorskip("adaptorch_mcp.thin_remote")
    local = next(
        t
        for t in engine.AdaptOrchMCPServer._tool_schemas()
        if t["name"] == "adaptorch_route_topology"
    )
    public = next(t for t in remote.discovery_catalog() if t["name"] == local["name"])
    assert public["inputSchema"] == local["inputSchema"]
