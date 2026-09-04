# mypy: disable-error-code="import-not-found"
# pyright: reportMissingImports=false
from __future__ import annotations

import json
from typing import Any

import pytest

from adaptorch_mcp.response_policy import sanitize_tool_response


def _sanitize(response: dict[str, Any], tool_name: str = "adaptorch_get_run") -> dict[str, Any]:
    return sanitize_tool_response(response, tool_name=tool_name)


def test_sanitize_tool_response_projects_tool_specific_result() -> None:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "run_id": "r1",
                            "status": "SUCCEEDED",
                            "diagnostics": {"private": True},
                            "diagnоstics": {"confusable": True},
                        }
                    ),
                    "annotations": {"private": True},
                }
            ],
            "structuredContent": {"routing_scores": {"hybrid": 0.9}},
            "_meta": {"private": True},
            "isError": False,
        },
    }

    sanitized = _sanitize(response)

    assert set(sanitized["result"]) == {"content", "isError", "structuredContent"}
    assert sanitized["result"]["isError"] is False
    assert sanitized["result"]["content"][0]["type"] == "text"
    expected = {"run_id": "r1", "status": "SUCCEEDED"}
    assert json.loads(sanitized["result"]["content"][0]["text"]) == expected
    assert sanitized["result"]["structuredContent"] == expected


@pytest.mark.parametrize(
    "content",
    [
        [{"type": "text", "text": "private threshold"}],
        [{"type": "text", "text": json.dumps("private threshold")}],
        [{"type": "text", "text": json.dumps({"diagnostics": {"private": True}})}],
        [{"type": "resource", "text": json.dumps({"run_id": "r1"})}],
        [
            {"type": "text", "text": json.dumps({"run_id": "r1"})},
            {"type": "text", "text": "private threshold"},
        ],
    ],
)
def test_sanitize_tool_response_fails_closed_for_unsupported_content(
    content: list[dict[str, Any]],
) -> None:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 8,
        "result": {"content": content},
    }

    sanitized = _sanitize(response)

    assert sanitized["result"]["isError"] is True
    assert json.loads(sanitized["result"]["content"][0]["text"]) == {
        "error": "unsupported tool response format"
    }


@pytest.mark.parametrize(
    ("tool_name", "payload"),
    [
        (
            "adaptorch_run",
            {"run_id": "r1", "artifact_urls": {"log": {"diagnostics": "private"}}},
        ),
        (
            "adaptorch_get_artifacts",
            {"run_id": "r1", "artifacts": {"log": {"diagnostics": "private"}}},
        ),
        (
            "adaptorch_get_artifacts",
            {"run_id": "r1", "artifacts": {"diagnоstics": "not-a-reference"}},
        ),
        (
            "adaptorch_list_runs",
            {
                "items": [{"run_id": "r1", "status": {"diagnostics": "private"}}],
                "total": 1,
                "page": 1,
                "page_size": 20,
                "has_next": False,
            },
        ),
    ],
)
def test_sanitize_tool_response_rejects_nested_untyped_values(
    tool_name: str,
    payload: dict[str, Any],
) -> None:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 9,
        "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
    }

    sanitized = _sanitize(response, tool_name)

    assert sanitized["result"]["isError"] is True


def test_get_run_rebuilds_structured_content_from_safe_projection() -> None:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 9,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "run_id": "r1",
                            "status": "SUCCEEDED",
                            "correctness_wall": {
                                "verdict": "PASS",
                                "blockers": [],
                                "advisories": [],
                                "evidence_notes": ["bounded evidence"],
                                "correctness_claim": False,
                                "selection_mutated": False,
                                "recommended_action": "observe",
                                "claim_boundary": {
                                    "is_correctness_proof": False,
                                    "is_active_selector": False,
                                    "is_shadow_observability_only": True,
                                    "real_docker_paired_required_for_promotion": True,
                                },
                            },
                            "diagnostics": {"private": True},
                        }
                    ),
                }
            ],
            "structuredContent": {"decision_trace": ["private"]},
            "_meta": {"private": True},
        },
    }

    sanitized = _sanitize(response)
    projected = json.loads(sanitized["result"]["content"][0]["text"])

    assert sanitized["result"]["structuredContent"] == projected
    assert "diagnostics" not in projected
    assert "decision_trace" not in projected


def test_non_get_run_tool_keeps_legacy_text_only_envelope() -> None:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 9,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "items": [],
                            "total": 0,
                            "page": 1,
                            "page_size": 20,
                            "has_next": False,
                        }
                    ),
                }
            ]
        },
    }

    sanitized = _sanitize(response, "adaptorch_list_runs")

    assert set(sanitized["result"]) == {"content", "isError"}


def test_sanitize_tool_response_projects_nested_run_list_items() -> None:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 9,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "items": [
                                {
                                    "run_id": "r1",
                                    "status": "SUCCEEDED",
                                    "diagnostics": {"private": True},
                                }
                            ],
                            "total": 1,
                            "page": 1,
                            "page_size": 20,
                            "has_next": False,
                        }
                    ),
                }
            ]
        },
    }

    sanitized = _sanitize(response, "adaptorch_list_runs")
    payload = json.loads(sanitized["result"]["content"][0]["text"])

    assert payload["items"] == [{"run_id": "r1", "status": "SUCCEEDED"}]


def test_sanitize_tool_response_removes_error_data_and_message() -> None:
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 10,
        "error": {
            "code": -32603,
            "message": "private threshold",
            "data": {"decision_trace": ["private"]},
        },
    }

    assert _sanitize(response) == {
        "jsonrpc": "2.0",
        "id": 10,
        "error": {"code": -32603, "message": "Tool execution failed"},
    }


def _control_plane_rejection(status_code: int, message: str) -> dict[str, Any]:
    """The engine's shape for a control-plane HTTP refusal (adaptorch.mcp_server)."""
    return {
        "jsonrpc": "2.0",
        "id": 11,
        "result": {
            "isError": True,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "error": "CONTROL_PLANE_REJECTED",
                            "status_code": status_code,
                            "message": message,
                        }
                    ),
                }
            ],
        },
    }


class TestControlPlaneRefusalReachesTheTenant:
    """A hosted deployment refuses keyless runs by naming the three provider headers.

    That sentence is the remedy; the remote profile must carry it through
    instead of collapsing it into "unsupported tool response format".
    """

    def test_a_401_byok_refusal_keeps_its_message(self) -> None:
        message = (
            "Control-plane HTTP error 401: byok_credentials_required: this deployment "
            "does not spend its own provider keys on your runs. Send yours with the "
            "X-Provider, X-Provider-Model and X-Provider-Key headers."
        )

        sanitized = _sanitize(_control_plane_rejection(401, message), "adaptorch_run")

        assert sanitized["result"]["isError"] is True
        body = json.loads(sanitized["result"]["content"][0]["text"])
        assert body == {
            "error": "CONTROL_PLANE_REJECTED",
            "status_code": 401,
            "message": message,
        }

    def test_a_403_plan_refusal_keeps_its_message(self) -> None:
        message = "Control-plane HTTP error 403: starter plan requires your own provider key"

        body = json.loads(
            _sanitize(_control_plane_rejection(403, message), "adaptorch_run")["result"][
                "content"
            ][0]["text"]
        )

        assert body["status_code"] == 403
        assert body["message"] == message

    @pytest.mark.parametrize("status_code", [400, 404, 429, 500, 503])
    def test_other_refusals_keep_the_code_but_not_the_operator_text(
        self, status_code: int
    ) -> None:
        body = json.loads(
            _sanitize(
                _control_plane_rejection(status_code, "internal detail /srv/x traceback"),
                "adaptorch_run",
            )["result"]["content"][0]["text"]
        )

        assert body == {"error": "CONTROL_PLANE_REJECTED", "status_code": status_code}

    def test_a_malformed_rejection_still_fails_closed(self) -> None:
        response = _control_plane_rejection(401, "x")
        response["result"]["content"][0]["text"] = json.dumps(
            {"error": "CONTROL_PLANE_REJECTED", "status_code": "401", "message": ["x"]}
        )

        body = json.loads(_sanitize(response, "adaptorch_run")["result"]["content"][0]["text"])

        assert body == {"error": "unsupported tool response format"}


@pytest.mark.parametrize(
    ("flag", "expected"),
    [(True, True), (False, False), ("true", False), (1, False), (None, False)],
    ids=["bool-true", "bool-false", "string-true", "int-one", "absent"],
)
def test_is_error_is_forwarded_only_for_a_real_boolean(flag: object, expected: bool) -> None:
    """The parent's ``isError`` is untrusted input: only the boolean ``True`` marks an error."""
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps({"run_id": "r1", "status": "QUEUED"})}]
    }
    if flag is not None:
        result["isError"] = flag

    sanitized = _sanitize({"jsonrpc": "2.0", "id": 12, "result": result}, "adaptorch_run")

    assert sanitized["result"]["isError"] is expected
