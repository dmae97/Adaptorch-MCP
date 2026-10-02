from __future__ import annotations

import io
import json
import unittest

from test_bridge import call, initialize, make_bridge

from adaptorch_mcp.contract import TOOL_NAMES
from adaptorch_mcp.protocol import FramingError, read_message, serve, write_message


class ProtocolTests(unittest.TestCase):
    def test_both_framings_initialize_to_submit(self) -> None:
        for framing in ("line", "content-length"):
            bridge, transport = make_bridge()
            source, sink = io.BytesIO(), io.BytesIO()
            requests = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "fixture", "version": "1"},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "adaptorch_run",
                        "arguments": {"prompt": "fixture", "wait_for_terminal": False},
                    },
                },
                {"jsonrpc": "2.0", "id": 4, "method": "shutdown"},
                {"jsonrpc": "2.0", "method": "exit"},
            ]
            for request in requests:
                write_message(source, request, framing)
            source.seek(0)
            self.assertEqual(serve(bridge, source, sink, framing), 0)
            sink.seek(0)
            responses = []
            while (raw := read_message(sink, framing)) is not None:
                responses.append(json.loads(raw))
            self.assertEqual([reply["id"] for reply in responses], [1, 2, 3, 4])
            self.assertEqual(len(responses[1]["result"]["tools"]), 9)
            self.assertEqual(len(transport.requests), 3)
            self.assertFalse(transport.requests[-1][0]["params"]["arguments"]["wait_for_terminal"])

    def test_wait_for_terminal_true_false_and_omitted(self) -> None:
        for value in [True, False, None]:
            bridge, transport = make_bridge()
            initialize(bridge)
            arguments = {"prompt": "fixture"}
            if value is not None:
                arguments["wait_for_terminal"] = value
            response = call(bridge, "tools/call", {"name": "adaptorch_run", "arguments": arguments})
            self.assertFalse(response["result"]["isError"])
            self.assertEqual(transport.requests[-1][0]["params"]["arguments"], arguments)
        schema = call(bridge, "tools/list")["result"]["tools"][0]["inputSchema"]
        self.assertEqual(schema["properties"]["wait_for_terminal"]["default"], True)
        self.assertNotIn("wait", schema["properties"])

    def test_metrics_are_local_and_annotations_truthful(self) -> None:
        bridge, transport = make_bridge()
        initialize(bridge)
        before = len(transport.requests)
        result = call(bridge, "tools/call", {"name": "adaptorch_server_metrics"})["result"]
        metrics = json.loads(result["content"][0]["text"])
        self.assertEqual(metrics["tool_calls"], 1)
        self.assertEqual(len(transport.requests), before)
        tools = {tool["name"]: tool for tool in call(bridge, "tools/list")["result"]["tools"]}
        self.assertEqual(set(tools), set(TOOL_NAMES))
        self.assertFalse(tools["adaptorch_server_metrics"]["annotations"]["idempotentHint"])
        self.assertFalse(tools["adaptorch_server_metrics"]["annotations"]["openWorldHint"])
        self.assertFalse(tools["adaptorch_capabilities"]["annotations"]["openWorldHint"])
        self.assertTrue(tools["adaptorch_cancel_run"]["annotations"]["destructiveHint"])

    def test_malformed_frames_stop_without_upstream(self) -> None:
        for value in [
            b"Content-Length: 1\r\nContent-Length: 1\r\n\r\nx",
            b"Content-Length: 2000000\r\n\r\n",
            b"Content-Length: -1\r\n\r\n",
            b"Content-Length: 4\r\n\r\n{}",
        ]:
            with self.assertRaises(FramingError):
                read_message(io.BytesIO(value), "content-length")
            bridge, transport = make_bridge()
            self.assertEqual(serve(bridge, io.BytesIO(value), io.BytesIO(), "content-length"), 2)
            self.assertFalse(transport.requests)

    def test_bad_json_batch_duplicate_and_nonfinite_never_forward(self) -> None:
        for value in [b"[]\n", b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b"\xff\n"]:
            bridge, transport = make_bridge()
            sink = io.BytesIO()
            serve(bridge, io.BytesIO(value), sink)
            self.assertEqual(json.loads(sink.getvalue())["error"]["code"], -32700)
            self.assertFalse(transport.requests)


if __name__ == "__main__":
    unittest.main()


class ArtifactAvailabilityTests(unittest.TestCase):
    def test_unsafe_or_private_artifact_labels_are_explicitly_unavailable(self) -> None:
        for artifacts in [
            {"report": "/srv/private/run-1/report.md"},
            {"/srv/private/report.md": "https://fixture.invalid/report.md"},
            {"report": "https://user:secret@fixture.invalid/report.md"},
            {"report": "file:///srv/private/report.md"},
            {"report": "javascript:alert(1)"},
            {"report": "https://fixture.invalid/report?token=unknown-capability"},
            {"report": "s3://fixture-bucket/report?signature=unknown-capability"},
            {"report": "gs://fixture-bucket/report?token=unknown-capability"},
            {"report": "adaptorch://runs/report?key=unknown-capability"},
        ]:
            bridge, transport = make_bridge()
            initialize(bridge)
            transport.override = {"run_id": "fixture-run-1", "artifacts": artifacts}
            response = call(
                bridge,
                "tools/call",
                {"name": "adaptorch_get_artifacts", "arguments": {"run_id": "fixture-run-1"}},
            )
            result = response["result"]
            self.assertTrue(result["isError"])
            payload = json.loads(result["content"][0]["text"])
            self.assertEqual(payload["error"], "ARTIFACT_REFERENCES_UNAVAILABLE")
            self.assertEqual(payload["run_id"], "fixture-run-1")
            self.assertNotIn("next_action", payload)
            self.assertFalse(payload["new_run_safe"])
            self.assertFalse(payload["automatic_retry"])
            self.assertNotIn("/srv/private", json.dumps(response))
            self.assertNotIn("user:secret", json.dumps(response))
            self.assertNotIn("unknown-capability", json.dumps(response))

    def test_valid_remote_artifacts_preserve_reference_without_fetching(self) -> None:
        bridge, transport = make_bridge()
        initialize(bridge)
        refs = {"report": "https://fixture.invalid/artifacts/report.md"}
        transport.override = {"run_id": "fixture-run-1", "artifacts": refs}
        result = call(
            bridge,
            "tools/call",
            {"name": "adaptorch_get_artifacts", "arguments": {"run_id": "fixture-run-1"}},
        )["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"])["artifacts"], refs)
        self.assertEqual(len(transport.requests), 3)
