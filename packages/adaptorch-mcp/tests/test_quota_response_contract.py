"""Quota exhaustion must remain actionable after the remote response projection."""

import json
from typing import Any

from adaptorch.n8n_connector import N8nQuotaExceededError

from adaptorch_mcp.hardening import HardenedMCPServer
from adaptorch_mcp.security_policy import REMOTE_EXPOSURE_PROFILE
from mcp_test_support import FakeBackend


def test_real_parent_quota_envelope_retains_bounded_usage_not_operator_text() -> None:
    class QuotaBackend(FakeBackend):
        def get_run(self, run_id: str) -> dict[str, Any]:
            raise N8nQuotaExceededError(
                message="private operator detail",
                usage={
                    "error": "QUOTA_EXCEEDED",
                    "limit": 1000,
                    "used": 1000,
                    "remaining": 0,
                    "upgrade_url": "/pricing",
                    "debug": "private",
                },
            )

    server = HardenedMCPServer(backend=QuotaBackend(), exposure_profile=REMOTE_EXPOSURE_PROFILE)
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "adaptorch_get_run", "arguments": {"run_id": "r1"}},
        }
    )
    assert response is not None and response["result"]["isError"] is True
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["error"] == "QUOTA_EXCEEDED"
    assert payload["usage"] == {
        "limit": 1000,
        "used": 1000,
        "remaining": 0,
        "upgrade_url": "/pricing",
    }
    assert "private" not in json.dumps(response)
    assert "structuredContent" not in response["result"]
