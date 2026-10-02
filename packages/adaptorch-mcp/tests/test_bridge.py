"""Neutral wire fixtures. No private engine implementation or network access."""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any
from unittest.mock import patch

from adaptorch_client.config import ClientConfig
from adaptorch_client.provider import ProviderCredential

from adaptorch_mcp.bridge import Bridge
from adaptorch_mcp.config import BridgeConfig
from adaptorch_mcp.contract import PROTOCOL_VERSION, TOOL_NAMES, input_schema


class FixtureTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[dict[str, Any], bool]] = []
        self.override: dict[str, Any] | None = None

    def request(self, message: dict[str, Any], *, submit: bool = False) -> dict[str, Any]:
        self.requests.append((copy.deepcopy(message), submit))
        method = message["method"]
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": "fixture", "version": "1"},
                "capabilities": {"tools": {}, "completions": {}},
            }
        elif method == "tools/list":
            tools = [
                {
                    "name": name,
                    "description": "untrusted upstream",
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
            tools += [{"name": "adaptorch_route_topology"}, {"name": "adaptorch_get_traces"}]
            result = {"tools": tools}
        else:
            payload = self.override or {
                "run_id": "fixture-run-1",
                "status": "QUEUED",
                "diagnostics": {"private": "do not expose"},
                "provider_key": "fixture-provider-secret",
            }
            result = {
                "content": [{"type": "text", "text": json.dumps(payload)}],
                "structuredContent": {"private": "do not expose"},
            }
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def make_bridge() -> tuple[Bridge, FixtureTransport]:
    transport = FixtureTransport()
    config = BridgeConfig(
        ClientConfig("https://fixture.invalid", "ado_fixture-tenant-secret"),
        ProviderCredential("openai", "fixture-model", "fixture-provider-secret"),
    )
    return Bridge(config, transport), transport


def call(
    bridge: Bridge, method: str, params: dict[str, Any] | None = None, identifier: int = 1
) -> dict[str, Any]:
    response = bridge.handle_message(
        {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}
    )
    assert response is not None
    return response


def initialize(bridge: Bridge) -> dict[str, Any]:
    return call(
        bridge,
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "fixture-client", "version": "1"},
        },
    )


class MinimalMilestone(unittest.TestCase):
    def setUp(self) -> None:
        self.socket_patch = patch("socket.socket.connect", side_effect=AssertionError("no sockets"))
        self.socket_patch.start()
        self.addCleanup(self.socket_patch.stop)

    def test_initialize_discover_read_submit(self) -> None:
        bridge, transport = make_bridge()
        response = initialize(bridge)
        self.assertNotIn("completions", response["result"]["capabilities"])
        tools = call(bridge, "tools/list")["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], list(TOOL_NAMES))
        read = call(
            bridge,
            "tools/call",
            {"name": "adaptorch_get_run", "arguments": {"run_id": "fixture-run-1"}},
        )["result"]
        self.assertEqual(read["structuredContent"], {"run_id": "fixture-run-1", "status": "QUEUED"})
        submit = call(
            bridge,
            "tools/call",
            {"name": "adaptorch_run", "arguments": {"prompt": "synthetic task"}},
        )["result"]
        self.assertFalse(submit["isError"])
        self.assertEqual(len(transport.requests), 4)
        self.assertEqual([submit for _, submit in transport.requests], [False, False, False, True])
        self.assertNotIn("private", json.dumps(read))
        self.assertNotIn("secret", json.dumps(submit))

    def test_run_subject_mismatch(self) -> None:
        bridge, transport = make_bridge()
        initialize(bridge)
        transport.override = {"run_id": "other-run", "status": "SUCCEEDED"}
        read = call(
            bridge,
            "tools/call",
            {"name": "adaptorch_get_run", "arguments": {"run_id": "fixture-run-1"}},
        )["result"]
        self.assertTrue(read["isError"])
        self.assertNotIn("other-run", json.dumps(read))

    def test_notifications_and_shutdown_never_forward(self) -> None:
        bridge, transport = make_bridge()
        initialize(bridge)
        size = len(transport.requests)
        for method in ["notifications/initialized", "notifications/cancelled", "tools/call"]:
            self.assertIsNone(bridge.handle_message({"jsonrpc": "2.0", "method": method}))
        self.assertEqual(call(bridge, "shutdown")["result"], None)
        self.assertEqual(len(transport.requests), size)
        self.assertIsNone(bridge.handle_message({"jsonrpc": "2.0", "method": "exit"}))
        self.assertTrue(bridge.exited)


if __name__ == "__main__":
    unittest.main()
