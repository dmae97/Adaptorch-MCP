"""Regressions found by independent MCP contract review."""

from __future__ import annotations

import json
from typing import Any

import pytest

from adaptorch_mcp.control_plane_backend import SafeControlPlaneConnector
from adaptorch_mcp.hardening import HardenedMCPServer
from test_control_plane_backend import PAYLOAD, PROVIDER_KEY, TENANT_KEY, Wire
from test_control_plane_backend import backend as backend
from test_control_plane_backend import wire as wire


@pytest.mark.parametrize("subject", [None, 7, True, "", "  "])
def test_bad_creation_subject_cannot_start_collection(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    subject: Any,
) -> None:
    wire.replies = [
        (201, json.dumps({"run_id": subject, "status": "QUEUED"}).encode()),
        (200, json.dumps({"run_id": str(subject), "status": "SUCCEEDED"}).encode()),
        (200, json.dumps({"run_id": str(subject), "artifacts": {}}).encode()),
    ]
    server = HardenedMCPServer(backend=backend, exposure_profile="remote")
    result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "adaptorch_run", "arguments": {"payload": PAYLOAD}},
        }
    )
    assert len(wire.calls) == 1
    assert result is not None and result["result"]["isError"] is True


@pytest.mark.parametrize("status", [401, 403])
def test_caller_fixable_refusal_keeps_bounded_redacted_guidance(
    backend: SafeControlPlaneConnector,
    wire: Wire,
    status: int,
) -> None:
    detail = (
        "byok_credentials_required: Send X-Provider, X-Provider-Model and X-Provider-Key. "
        + TENANT_KEY
        + " "
        + PROVIDER_KEY
    )
    wire.replies = [(status, json.dumps({"detail": detail}).encode())]
    server = HardenedMCPServer(backend=backend, exposure_profile="remote")
    result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "adaptorch_run",
                "arguments": {"payload": PAYLOAD, "wait_for_terminal": False},
            },
        }
    )
    assert result is not None and result["result"]["isError"] is True
    payload = json.loads(result["result"]["content"][0]["text"])
    assert "byok_credentials_required" in payload["message"]
    assert "X-Provider-Key" in payload["message"]
    assert TENANT_KEY not in json.dumps(result) and PROVIDER_KEY not in json.dumps(result)
    assert len(wire.calls) == 1
