from __future__ import annotations

import json

import pytest
from client_test_support import JSONMapping, LocalAPIServer

from adaptorch_client import (
    NAVIGATION_ALGORITHMS,
    AdaptOrchAPIError,
    AdaptOrchClient,
    ClientConfig,
    EvidenceNavigation,
    PayloadResult,
)

PACK: list[JSONMapping] = [
    {"source_id": "market.pdf", "page": 1, "chunk": "a", "evidence_text": "Prices move."}
]


def _client(api: LocalAPIServer) -> AdaptOrchClient:
    return AdaptOrchClient(ClientConfig(api_url=api.api_url, api_key="test-api-key"))


def _navigation(version: str = "graph_v5") -> JSONMapping:
    return {
        "schema": "graphrag-evidence-navigation-v2",
        "navigation_version": version,
        "classification": {"kind": "factoid"},
        "plan": {"subtasks": []},
        "evaluation": {"semantic_support": "NOT_EVALUATED", "candidates": []},
    }


def test_navigate_evidence_posts_the_pack_and_types_the_result(
    local_api: LocalAPIServer,
) -> None:
    local_api.enqueue_json(_navigation())

    result = _client(local_api).navigate_evidence("How do prices move?", PACK)

    request = local_api.requests[0]
    assert (request.method, request.path) == ("POST", "/v1/navigation/evidence")
    assert json.loads(request.body) == {
        "question": "How do prices move?",
        "evidence_pack": PACK,
        "algorithm_version": "graph_v5",
    }
    assert isinstance(result, PayloadResult)
    assert result.navigation_version == "graph_v5"
    assert result.semantic_support == "NOT_EVALUATED"
    assert result.to_payload() == _navigation()


def test_navigate_evidence_forwards_graph_v4(local_api: LocalAPIServer) -> None:
    local_api.enqueue_json(_navigation("graph_v4"))
    result = _client(local_api).navigate_evidence("q", PACK, algorithm_version="graph_v4")
    assert json.loads(local_api.requests[0].body)["algorithm_version"] == "graph_v4"
    assert result.navigation_version == "graph_v4"


def test_unknown_algorithm_is_refused_before_any_request(local_api: LocalAPIServer) -> None:
    with pytest.raises(ValueError, match="algorithm_version"):
        _client(local_api).navigate_evidence("q", PACK, algorithm_version="graph_v9")
    assert local_api.requests == []


def test_a_response_that_claims_semantic_support_is_rejected(local_api: LocalAPIServer) -> None:
    payload = _navigation()
    payload["evaluation"] = {"semantic_support": "SUPPORTED", "candidates": []}
    local_api.enqueue_json(payload)
    with pytest.raises(AdaptOrchAPIError):
        _client(local_api).navigate_evidence("q", PACK)


def test_algorithms_constant_matches_the_engine_vocabulary() -> None:
    assert NAVIGATION_ALGORITHMS == ("graph_v4", "graph_v5")
    assert EvidenceNavigation.__name__ in __import__("adaptorch_client").__all__
