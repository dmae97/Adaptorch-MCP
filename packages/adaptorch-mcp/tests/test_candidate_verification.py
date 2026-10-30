"""Provider-free verification uses a closed response contract, not engine imports."""
from __future__ import annotations

import json
from typing import Any

from adaptorch_client.provider import ProviderCredential
from adaptorch_client.transport import RequestSpec
from adaptorch_mcp.thin_remote import RemoteMCPServer


def report() -> dict[str, Any]:
    return {
        "schema_version": "candidate-verification/v1", "verification_id": "a" * 64,
        "repository_id": "calc", "revision": "b" * 40, "base_revision": "c" * 40,
        **{key: "d" * 64 for key in (
            "candidate_sha256", "subject_sha256", "verifier_bundle_sha256", "profile_sha256",
            "environment_sha256", "parameters_sha256", "report_sha256",
        )},
        "verifier_id": "pytest-scope", "verifier_version": "1", "status": "COMPLETED",
        "outcome": "PASS", "attempt_id": "attempt-one",
        "required_checks": ["tests.test_calc::test_add"],
        "provider_calls": 0, "model_fallback": False, "correctness_proof": False,
        "release_authorized": False, "harness_isolation": "in_process", "network": "unshared",
        "generation_identity": "unknown",
    }


class Transport:
    def __init__(self, value: dict[str, Any]) -> None:
        self.specs: list[RequestSpec] = []
        self.value = value

    def close(self) -> None:
        pass

    def request(self, spec: RequestSpec) -> dict[str, Any]:
        self.specs.append(spec)
        assert spec.payload is not None
        return {"jsonrpc": "2.0", "id": spec.payload["id"], "result": {
            "content": [{"type": "text", "text": json.dumps(self.value)}],
            "isError": False,
        }}


def call(server: RemoteMCPServer, tool: str, arguments: dict[str, str]) -> dict[str, Any]:
    response = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": tool, "arguments": arguments}})
    assert response is not None
    return response


def test_verification_never_carries_byok_and_strips_private_fields() -> None:
    value = report()
    transport = Transport({**value, "diagnostics": {"secret": "private"}})
    server = RemoteMCPServer(
        transport, provider_credential=ProviderCredential("openai", "x", "secret"),
    )
    result = call(server, "adaptorch_verify_candidate", {
        "repository_id": "calc", "revision": "b" * 40, "idempotency_key": "candidate-one",
    })
    assert "error" not in result and not result["result"].get("isError"), result
    assert json.loads(result["result"]["content"][0]["text"]) == value
    assert transport.specs[-1].provider_credential is None
    fetched = call(server, "adaptorch_get_verification_report", {"verification_id": "a" * 64})
    assert not fetched["result"].get("isError"), fetched
    assert transport.specs[-1].provider_credential is None


def test_wrong_report_identity_and_false_pass_are_rejected() -> None:
    for changed in ({"verification_id": "e" * 64}, {"provider_calls": 1},
                    {"status": "RUNNING", "outcome": "PASS"}, {"outcome": "made-up"}):
        server = RemoteMCPServer(Transport({**report(), **changed}))
        response = call(server, "adaptorch_get_verification_report", {"verification_id": "a" * 64})
        assert response.get("error") or response["result"].get("isError"), response
