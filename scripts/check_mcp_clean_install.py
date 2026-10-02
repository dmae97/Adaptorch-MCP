"""Run from the built-wheel isolated venv, never from the source checkout."""
# ruff: noqa: E402 -- Install socket/core-import guards before importing the tested wheel.

from __future__ import annotations

import importlib
import importlib.abc
import importlib.metadata
import io
import json
import os
import pkgutil
import socket
import sys
from pathlib import Path


class NoCore(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "adaptorch" or fullname.startswith("adaptorch."):
            raise AssertionError("Private core import attempted")
        return None


def blocked(*args, **kwargs):
    raise AssertionError("External network forbidden")


sys.meta_path.insert(0, NoCore())
for name in ["create_connection", "getaddrinfo"]:
    setattr(socket, name, blocked)
for name in ["connect", "connect_ex", "bind"]:
    setattr(socket.socket, name, blocked)

import adaptorch_mcp
from adaptorch_client.config import ClientConfig
from adaptorch_mcp.bridge import Bridge
from adaptorch_mcp.config import BridgeConfig
from adaptorch_mcp.contract import PROTOCOL_VERSION, TOOL_NAMES, input_schema
from adaptorch_mcp.protocol import read_message, serve, write_message

assert str(Path(adaptorch_mcp.__file__).resolve()).startswith(sys.prefix + os.sep)
assert sys.prefix != sys.base_prefix
assert "include-system-site-packages = false" in (Path(sys.prefix) / "pyvenv.cfg").read_text()
for module in pkgutil.iter_modules(adaptorch_mcp.__path__):
    if module.name != "__main__":
        importlib.import_module("adaptorch_mcp." + module.name)
assert not any(name == "adaptorch" or name.startswith("adaptorch.") for name in sys.modules)
assert importlib.metadata.version("adaptorch-client") == "0.1.2"
assert importlib.metadata.requires("adaptorch-mcp")[0] == "adaptorch-client==0.1.2"


class Wire:
    def __init__(self):
        self.requests = []

    def request(self, message, *, submit=False):
        self.requests.append((message, submit))
        if message["method"] == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": "fixture", "version": "1"},
                "capabilities": {},
            }
        elif message["method"] == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": "fixture",
                        "inputSchema": input_schema(name),
                        "annotations": {
                            "title": name,
                            "readOnlyHint": True,
                            "destructiveHint": False,
                            "idempotentHint": True,
                            "openWorldHint": True,
                        },
                    }
                    for name in TOOL_NAMES
                ]
            }
        else:
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "run_id": "synthetic-1",
                                "status": "QUEUED",
                                "diagnostics": {"secret": "hidden"},
                            }
                        ),
                    }
                ]
            }
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}


for framing in ["line", "content-length"]:
    wire = Wire()
    bridge = Bridge(BridgeConfig(ClientConfig("https://fixture.invalid", "ado_fake")), wire)
    source, sink = io.BytesIO(), io.BytesIO()
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "fixture", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "adaptorch_get_run", "arguments": {"run_id": "synthetic-1"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "adaptorch_run",
                "arguments": {"prompt": "synthetic", "wait_for_terminal": False},
            },
        },
        {"jsonrpc": "2.0", "id": 5, "method": "shutdown"},
        {"jsonrpc": "2.0", "method": "exit"},
    ]
    for message in messages:
        write_message(source, message, framing)
    source.seek(0)
    assert serve(bridge, source, sink, framing) == 0
    sink.seek(0)
    replies = []
    while (raw := read_message(sink, framing)) is not None:
        replies.append(json.loads(raw))
    assert [reply["id"] for reply in replies] == [1, 2, 3, 4, 5]
    assert [tool["name"] for tool in replies[1]["result"]["tools"]] == list(TOOL_NAMES)
    assert replies[2]["result"]["structuredContent"] == {
        "run_id": "synthetic-1",
        "status": "QUEUED",
    }
    assert not replies[3]["result"]["isError"]
    assert [submit for _, submit in wire.requests] == [False, False, False, True]
    assert "diagnostics" not in sink.getvalue().decode()

print(
    json.dumps(
        {
            "ok": True,
            "python": sys.version.split()[0],
            "installed_package": str(Path(adaptorch_mcp.__file__).resolve()),
            "system_site_packages": False,
            "private_imports": False,
            "socket_operations": "blocked",
            "framings": ["line", "content-length"],
            "initialize_tools_read_submit": True,
            "distributions": sorted(
                (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
            ),
        },
        indent=2,
    )
)
