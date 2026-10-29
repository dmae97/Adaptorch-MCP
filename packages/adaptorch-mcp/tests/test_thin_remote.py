from __future__ import annotations

import io
import json
import subprocess
import sys
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from adaptorch_client.provider import ProviderCredential
from adaptorch_client.transport import RequestSpec
from adaptorch_mcp.thin_http import create_remote_http_app
from adaptorch_mcp.thin_remote import RemoteMCPServer
from adaptorch_mcp.thin_runtime import run_remote_main
from adaptorch_mcp.thin_stdio import read_message, serve_stdio, write_message

_ANNOTATIONS = {
    "title": "Remote tool",
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


class _Transport:
    def __init__(self) -> None:
        self.specs: list[RequestSpec] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def request(self, spec: RequestSpec) -> dict[str, Any]:
        self.specs.append(spec)
        request = spec.payload or {}
        request_id = request.get("id")
        method = request.get("method")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "serverInfo": {"name": "private-core", "version": "internal"},
                    "capabilities": {"tools": {}, "completions": {}},
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "adaptorch_run",
                            "description": "Run remotely",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"prompt": {"type": "string"}},
                                "additionalProperties": False,
                            },
                            "annotations": _ANNOTATIONS,
                        },
                        {
                            "name": "adaptorch_get_traces",
                            "description": "Internal only",
                            "inputSchema": {
                                "type": "object",
                                "additionalProperties": False,
                            },
                            "annotations": _ANNOTATIONS,
                        },
                    ]
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": "{}"}],
            },
        }


def _call(server: RemoteMCPServer, method: str, **params: Any) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if method == "tools/call":
        message["params"] = {"name": params.pop("name"), "arguments": params}
    elif params:
        message["params"] = params
    response = server.handle_message(message)
    assert response is not None
    return response


def test_remote_tools_are_projected_without_a_local_engine() -> None:
    transport = _Transport()
    server = RemoteMCPServer(transport)
    response = _call(server, "tools/list")
    names = [tool["name"] for tool in response["result"]["tools"]]
    assert names == ["adaptorch_run"]
    assert transport.specs[0].path == "/v1/mcp"


def test_byok_is_scoped_to_run_and_unknown_tools_do_not_leave_the_process() -> None:
    transport = _Transport()
    credential = ProviderCredential("openai", "gpt-test", "secret")
    server = RemoteMCPServer(transport, provider_credential=credential)
    _call(server, "tools/call", name="adaptorch_run", prompt="test")
    assert transport.specs[-1].provider_credential is credential
    before = len(transport.specs)
    response = _call(server, "tools/call", name="adaptorch_get_traces")
    assert response["error"]["code"] == -32601
    assert len(transport.specs) == before
    rejected = _call(
        server,
        "tools/call",
        name="adaptorch_run",
        prompt="test",
        verification_commands=["pytest"],
    )
    assert rejected["error"]["code"] == -32602
    assert len(transport.specs) == before


def test_initialize_hides_upstream_server_identity() -> None:
    server = RemoteMCPServer(_Transport())
    response = _call(server, "initialize")
    assert response["result"]["serverInfo"]["name"] == "adaptorch-mcp"
    assert "completions" not in response["result"]["capabilities"]


def test_public_package_import_does_not_load_private_engine() -> None:
    script = """
import sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if name == 'adaptorch' or name.startswith('adaptorch.'):
            raise ModuleNotFoundError('private engine import attempted')
        return None
sys.meta_path.insert(0, Block())
sys.path.insert(0, 'packages/adaptorch-mcp/src')
sys.path.insert(0, 'packages/adaptorch-client/src')
import adaptorch_mcp.cli
import adaptorch_mcp.thin_runtime
print('ok')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=".",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_stdio_and_http_use_only_the_remote_transport() -> None:
    transport = _Transport()
    server = RemoteMCPServer(transport)
    input_stream = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n')
    output_stream = io.BytesIO()
    assert serve_stdio(server, input_stream=input_stream, output_stream=output_stream) == 0
    assert json.loads(output_stream.getvalue())["result"]["tools"][0]["name"] == "adaptorch_run"
    assert transport.closed
    framed = io.BytesIO()
    write_message(framed, {"jsonrpc": "2.0", "id": 1}, framing="content-length")
    assert read_message(io.BytesIO(framed.getvalue()), framing="content-length") == {
        "jsonrpc": "2.0",
        "id": 1,
    }
    http_server = RemoteMCPServer(_Transport())
    with TestClient(
        create_remote_http_app(server=http_server, auth_token="client-token")
    ) as client:
        unauthorized = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert unauthorized.status_code == 401
        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer client-token"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 200
        assert response.json()["result"]["tools"][0]["name"] == "adaptorch_run"


def test_cli_constructs_remote_client_without_contacting_it() -> None:
    server = RemoteMCPServer(_Transport())
    with (
        patch(
            "adaptorch_mcp.thin_runtime.RemoteMCPServer.from_config", return_value=server
        ) as factory,
        patch("adaptorch_mcp.thin_stdio.serve_stdio", return_value=0) as serve,
    ):
        result = run_remote_main([], env={"ADAPTORCH_CONTROL_PLANE_TOKEN": "service-token"})
    assert result == 0
    assert factory.call_args.kwargs["api_token"] == "service-token"
    assert serve.call_args.kwargs["framing"] == "newline"
