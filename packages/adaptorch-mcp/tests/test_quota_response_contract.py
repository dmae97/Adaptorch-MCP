"""Quota exhaustion must remain actionable after the remote response projection."""

import json
from typing import Any

import pytest
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


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil.example/pay",  # another origin
        "//evil.example/pay",  # protocol-relative: same scheme, another origin
        "/\\evil.example",  # browsers normalise the backslash to a slash
        "javascript:alert(1)",  # not a path at all
        "pricing",  # relative to wherever the client happens to be
        "/pricing\nX",  # a control character smuggled into the link
        "/" + "a" * 3000,  # unbounded
    ],
)
def test_an_upgrade_url_that_leaves_the_origin_is_never_forwarded(hostile: str) -> None:
    # The link comes from the control plane, but an MCP client will offer it to a person who
    # is about to pay. Only a same-origin path may reach them: anything else voids the whole
    # projection rather than being trimmed, so a hostile value cannot ride in a valid envelope.
    class QuotaBackend(FakeBackend):
        def get_run(self, run_id: str) -> dict[str, Any]:
            raise N8nQuotaExceededError(
                message="private operator detail",
                usage={
                    "error": "QUOTA_EXCEEDED",
                    "limit": 10,
                    "used": 10,
                    "remaining": 0,
                    "upgrade_url": hostile,
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

    assert response is not None
    text = response["result"]["content"][0]["text"]
    assert json.loads(text).get("error") != "QUOTA_EXCEEDED"
    assert "upgrade_url" not in text
    assert "evil.example" not in text and "javascript" not in text
