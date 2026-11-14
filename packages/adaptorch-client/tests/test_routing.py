from __future__ import annotations

import json
from typing import Any

import pytest
from client_test_support import LocalAPIServer

from adaptorch_client import AdaptOrchAPIError, AdaptOrchClient, ClientConfig


def advice() -> dict[str, Any]:
    return {
        "topology": "parallel",
        "reason": "independent tasks",
        "stages": [["a"]],
        "features": {"node_count": 1, "edge_count": 0},
        "pesco": {
            "schema": "pesco.initial-routing/v1",
            "mode": "advisory",
            "state": "incumbent_no_policy",
            "baseline_topology": "parallel",
            "selected_topology": "parallel",
            "changed": False,
            "allocation_verified": False,
            "alpha_spent_by_route": False,
            "execution_authorized": False,
            "is_correctness_proof": False,
            "checks": [{"check": "policy_present", "passed": False}],
        },
    }


def envelope(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "route-topology",
        "result": {
            "content": [{"type": "text", "text": json.dumps(value)}],
        },
    }


def test_sdk_routes_through_authenticated_hosted_engine(local_api: LocalAPIServer) -> None:
    payload = advice()
    payload["private_engine_state"] = "must-not-escape"
    local_api.enqueue_json(envelope(payload))
    config = ClientConfig(api_url=local_api.api_url, api_key="ado_test_local")
    with AdaptOrchClient(config) as client:
        result = client.route_topology({"subtasks": [{"id": "a", "description": "inspect"}]})
    request = local_api.requests[0]
    assert (request.method, request.path) == ("POST", "/v1/mcp")
    assert {k.lower(): v for k, v in request.headers.items()}["x-api-key"] == "ado_test_local"
    sent = json.loads(request.body)
    assert sent["params"]["name"] == "adaptorch_route_topology"
    assert sent["params"]["arguments"]["prefer_ensemble_singleton"] is False
    assert result.topology == "parallel"
    assert result.to_payload() == advice()


@pytest.mark.parametrize(
    "invalid",
    [
        {"subtasks": []},
        {"subtasks": [{}] * 257},
        {"subtasks": [{}], "pesco_policy": {"qualified": True}},
        {"subtasks": [{}], "prefer_ensemble_singleton": 1},
        {"subtasks": [{}], "measured_quality_gain": float("nan")},
    ],
)
def test_sdk_rejects_untrusted_policy_and_unbounded_work_before_io(
    local_api: LocalAPIServer,
    invalid: dict[str, Any],
) -> None:
    client = AdaptOrchClient(ClientConfig(api_url=local_api.api_url, api_key="unused"))
    with pytest.raises(ValueError):
        client.route_topology(invalid)
    assert local_api.requests == []


@pytest.mark.parametrize("fault", ["authorized", "topology", "identity", "error"])
def test_sdk_refuses_forged_advice(local_api: LocalAPIServer, fault: str) -> None:
    value = advice()
    if fault == "authorized":
        value["pesco"]["execution_authorized"] = True
    if fault == "topology":
        value["pesco"]["selected_topology"] = "sequential"
    response = envelope(value)
    if fault == "identity":
        response["id"] = "other-request"
    if fault == "error":
        response["result"]["isError"] = True
    local_api.enqueue_json(response)
    client = AdaptOrchClient(ClientConfig(api_url=local_api.api_url, api_key="unused"))
    with pytest.raises(AdaptOrchAPIError):
        client.route_topology({"subtasks": [{"id": "a"}]})
