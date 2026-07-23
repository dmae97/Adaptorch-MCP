from __future__ import annotations

import json
from typing import Any

import pytest

from adaptorch_mcp.output_schema import project_tool_output
from adaptorch_mcp.response_policy import sanitize_tool_response


def _valid_wall() -> dict[str, Any]:
    return {
        "verdict": "ADVISORY",
        "blockers": [],
        "advisories": ["real_docker_paired_evidence_missing"],
        "evidence_notes": ["shadow observability only"],
        "correctness_claim": False,
        "selection_mutated": False,
        "recommended_action": "deep_check",
        "claim_boundary": {
            "is_correctness_proof": False,
            "is_active_selector": False,
            "is_shadow_observability_only": True,
            "real_docker_paired_required_for_promotion": True,
        },
    }


def test_get_run_projection_exposes_bounded_correctness_wall() -> None:
    wall = _valid_wall()
    wall["private_selector_scores"] = {"candidate-a": 0.9}

    projected = project_tool_output(
        "adaptorch_get_run",
        {
            "run_id": "run-wall-1",
            "status": "SUCCEEDED",
            "correctness_wall": wall,
            "diagnostics": {"private": True},
        },
    )

    assert projected == {
        "run_id": "run-wall-1",
        "status": "SUCCEEDED",
        "correctness_wall": _valid_wall(),
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("correctness_claim",), True),
        (("claim_boundary", "is_correctness_proof"), True),
        (("claim_boundary", "is_active_selector"), True),
    ],
)
def test_get_run_projection_fails_closed_on_forbidden_claims(
    path: tuple[str, ...],
    value: bool,
) -> None:
    wall = _valid_wall()
    if len(path) == 1:
        wall[path[0]] = value
    else:
        wall["claim_boundary"][path[1]] = value

    projected = project_tool_output(
        "adaptorch_get_run",
        {"run_id": "run-wall-2", "status": "SUCCEEDED", "correctness_wall": wall},
    )

    assert projected == {
        "run_id": "run-wall-2",
        "status": "SUCCEEDED",
        "correctness_wall": None,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("blockers", [f"blocker-{index}" for index in range(17)]),
        ("advisories", ["x" * 257]),
        ("evidence_notes", [""]),
    ],
)
def test_get_run_projection_rejects_oversized_or_empty_wall_context(
    field: str,
    value: list[str],
) -> None:
    wall = _valid_wall()
    wall[field] = value

    projected = project_tool_output(
        "adaptorch_get_run",
        {"run_id": "run-wall-3", "status": "SUCCEEDED", "correctness_wall": wall},
    )

    assert projected is not None
    assert projected["correctness_wall"] is None


def test_get_run_projection_preserves_legacy_parent_shape_when_wall_is_absent() -> None:
    projected = project_tool_output(
        "adaptorch_get_run",
        {"run_id": "legacy-run", "status": "SUCCEEDED", "diagnostics": {"private": True}},
    )

    assert projected == {"run_id": "legacy-run", "status": "SUCCEEDED"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("verdict", []),
        ("verdict", {}),
        ("verdict", 1),
        ("verdict", True),
        ("verdict", None),
        ("recommended_action", []),
        ("recommended_action", {}),
        ("recommended_action", 1),
        ("recommended_action", True),
        ("recommended_action", None),
    ],
)
def test_get_run_fails_closed_on_non_string_wall_enums(field: str, value: Any) -> None:
    wall = _valid_wall()
    wall[field] = value
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 8,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "run_id": "r-malformed-wall",
                            "status": "SUCCEEDED",
                            "correctness_wall": wall,
                        }
                    ),
                }
            ]
        },
    }

    sanitized = sanitize_tool_response(response, tool_name="adaptorch_get_run")
    projected = json.loads(sanitized["result"]["content"][0]["text"])

    assert sanitized["result"]["isError"] is False
    assert projected["correctness_wall"] is None
    assert sanitized["result"]["structuredContent"] == projected


def test_current_parent_pass_wall_survives_public_projection() -> None:
    shadow_report = pytest.importorskip("adaptorch.cek.shadow_report")
    control_plane_models = pytest.importorskip("adaptorch.control_plane.models")
    evidence_notes = tuple(f"parent-evidence-{index}" for index in range(11))
    wall = shadow_report.CorrectnessWallResult(
        verdict=shadow_report.CorrectnessWallVerdict.PASS,
        evidence_notes=evidence_notes,
        recommended_action="observe",
    )
    record = control_plane_models.RunRecord(
        run_id="run-parent-wall",
        payload={},
        synthesis_mode="robust",
        model=None,
        trace=False,
        budget_policy=None,
        created_at="2026-07-14T00:00:00+00:00",
        status="SUCCEEDED",
        result_status="OK",
        diagnostics={"correctness_wall": wall.to_payload()},
    )

    projected = project_tool_output("adaptorch_get_run", record.summary_payload())

    assert projected is not None
    assert projected["correctness_wall"] is not None
    assert projected["correctness_wall"]["verdict"] == "PASS"
    assert projected["correctness_wall"]["evidence_notes"] == list(evidence_notes)


def test_run_list_projection_does_not_gain_correctness_wall() -> None:
    projected = project_tool_output(
        "adaptorch_list_runs",
        {
            "items": [
                {
                    "run_id": "run-wall-4",
                    "status": "SUCCEEDED",
                    "correctness_wall": _valid_wall(),
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 20,
            "has_next": False,
        },
    )

    assert projected is not None
    assert projected["items"] == [{"run_id": "run-wall-4", "status": "SUCCEEDED"}]
