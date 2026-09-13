"""Projection tests for the B2C first-run receipt on the public MCP surface.

The consumer question is "did my run work, did it stay in budget, was it
verified". The wrapper answers it only in the engine's vocabulary; anything else
is dropped rather than forwarded, including a receipt that claims the beta is
finished.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from adaptorch_mcp.correctness_wall_output import get_run_output_schema
from adaptorch_mcp.first_run_receipt_output import (
    BUDGET_STATES,
    CLAIM_BOUNDARY_FIELDS,
    CLAIM_STATES,
    MAX_POSITIONING_LENGTH,
    RECEIPT_VERDICTS,
    VERIFICATION_STATES,
    project_first_run_receipt,
)
from adaptorch_mcp.output_schema import project_tool_output


def _claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "state": "beta_only",
        "positioning": "hosted_beta_or_local_quickstart",
        **CLAIM_BOUNDARY_FIELDS,
    }
    claims.update(overrides)
    return claims


def _receipt(**overrides: Any) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "verdict": "OK",
        "budget_state": "within_cap",
        "verification_state": "passed",
        "claims": _claims(),
    }
    receipt.update(overrides)
    return receipt


def _run(**overrides: Any) -> dict[str, Any]:
    run: dict[str, Any] = {
        "run_id": "run_20260804_demo",
        "status": "SUCCEEDED",
        "first_run_receipt": _receipt(),
    }
    run.update(overrides)
    return run


# --------------------------------------------------------------------------
# Accepted shape
# --------------------------------------------------------------------------


def test_valid_receipt_round_trips() -> None:
    assert project_first_run_receipt(_receipt()) == _receipt()


def test_projection_drops_keys_the_parent_adds() -> None:
    projected = project_first_run_receipt(
        _receipt(
            artifact_path="/srv/adaptorch/run_1/first_run_receipt.json",
            prompt_hmac_sha256="b" * 64,
            redacted_preview="my private prompt",
        )
    )

    assert projected is not None
    assert set(projected) == {
        "schema_version",
        "verdict",
        "budget_state",
        "verification_state",
        "claims",
    }


def test_projection_leaks_no_parent_supplied_paths_or_prompt_text() -> None:
    rendered = json.dumps(
        project_first_run_receipt(
            _receipt(
                artifact_path="/srv/adaptorch/run_1/first_run_receipt.json",
                redacted_preview="my private prompt",
            )
        )
    )

    assert "/srv/adaptorch" not in rendered
    assert "my private prompt" not in rendered


@pytest.mark.parametrize("verdict", RECEIPT_VERDICTS)
def test_every_verdict_projects(verdict: str) -> None:
    projected = project_first_run_receipt(_receipt(verdict=verdict))

    assert projected is not None
    assert projected["verdict"] == verdict


@pytest.mark.parametrize("state", BUDGET_STATES)
def test_every_budget_state_projects(state: str) -> None:
    projected = project_first_run_receipt(_receipt(budget_state=state))

    assert projected is not None
    assert projected["budget_state"] == state


@pytest.mark.parametrize("state", VERIFICATION_STATES)
def test_every_verification_state_projects(state: str) -> None:
    projected = project_first_run_receipt(_receipt(verification_state=state))

    assert projected is not None
    assert projected["verification_state"] == state


def test_receipt_without_claims_still_projects() -> None:
    receipt = _receipt()
    del receipt["claims"]

    projected = project_first_run_receipt(receipt)

    assert projected is not None
    assert "claims" not in projected


# --------------------------------------------------------------------------
# Fail-closed rejection
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"verdict": "GREAT"}, id="unknown-verdict"),
        pytest.param({"verdict": "ok"}, id="wrong-case-verdict"),
        pytest.param({"budget_state": "probably_fine"}, id="unknown-budget-state"),
        pytest.param({"verification_state": "maybe"}, id="unknown-verification-state"),
        pytest.param({"schema_version": 0}, id="non-positive-schema-version"),
        pytest.param({"schema_version": True}, id="bool-as-schema-version"),
        pytest.param({"schema_version": "1"}, id="string-schema-version"),
    ],
)
def test_malformed_receipts_are_rejected(overrides: dict[str, Any]) -> None:
    assert project_first_run_receipt(_receipt(**overrides)) is None


@pytest.mark.parametrize("field", sorted(CLAIM_BOUNDARY_FIELDS))
def test_an_overclaiming_receipt_is_rejected(field: str) -> None:
    """A beta must not tell a paying consumer it is launch-ready."""
    assert project_first_run_receipt(_receipt(claims=_claims(**{field: True}))) is None


@pytest.mark.parametrize(
    "claim_overrides",
    [
        pytest.param({"state": "generally_available"}, id="unknown-claim-state"),
        pytest.param({"positioning": ""}, id="empty-positioning"),
        pytest.param({"positioning": 7}, id="non-string-positioning"),
        pytest.param({"positioning": "x" * (MAX_POSITIONING_LENGTH + 1)}, id="long-positioning"),
    ],
)
def test_malformed_claims_are_rejected(claim_overrides: dict[str, Any]) -> None:
    assert project_first_run_receipt(_receipt(claims=_claims(**claim_overrides))) is None


@pytest.mark.parametrize("value", [None, "OK", 3, ["OK"]])
def test_non_mapping_receipts_are_rejected(value: Any) -> None:
    assert project_first_run_receipt(value) is None


# --------------------------------------------------------------------------
# get_run wiring
# --------------------------------------------------------------------------


def test_get_run_projects_the_receipt_for_the_consumer() -> None:
    projected = project_tool_output("adaptorch_get_run", _run())

    assert projected is not None
    assert projected["first_run_receipt"] == _receipt()


def test_get_run_tolerates_runs_without_a_receipt() -> None:
    run = _run()
    del run["first_run_receipt"]

    projected = project_tool_output("adaptorch_get_run", run)

    assert projected is not None
    assert "first_run_receipt" not in projected


def test_get_run_nulls_a_malformed_receipt_but_keeps_the_run_summary() -> None:
    projected = project_tool_output(
        "adaptorch_get_run", _run(first_run_receipt=_receipt(verdict="GREAT"))
    )

    assert projected is not None
    assert projected["run_id"] == "run_20260804_demo"
    assert projected["first_run_receipt"] is None


def test_get_run_passes_through_a_null_receipt_for_unfinished_runs() -> None:
    projected = project_tool_output("adaptorch_get_run", _run(first_run_receipt=None))

    assert projected is not None
    assert projected["first_run_receipt"] is None


# --------------------------------------------------------------------------
# Advertised output schema
# --------------------------------------------------------------------------


def test_get_run_output_schema_declares_the_receipt() -> None:
    schema = get_run_output_schema()["properties"]["first_run_receipt"]

    assert schema["type"] == ["object", "null"]
    # Strictly the boolean False: a falsy schema fragment like {} would leave the
    # object open, so type and value are both checked.
    assert isinstance(schema["additionalProperties"], bool)
    assert not schema["additionalProperties"]
    assert schema["properties"]["verdict"]["enum"] == list(RECEIPT_VERDICTS)
    assert schema["properties"]["budget_state"]["enum"] == list(BUDGET_STATES)
    assert schema["properties"]["verification_state"]["enum"] == list(VERIFICATION_STATES)
    assert schema["properties"]["claims"]["properties"]["state"]["enum"] == list(CLAIM_STATES)
    for field, expected in CLAIM_BOUNDARY_FIELDS.items():
        assert schema["properties"]["claims"]["properties"][field] == {"const": expected}


def test_advertised_schema_accepts_every_projected_receipt_key() -> None:
    """Whatever the projection emits must be declared, or clients see schema errors."""
    projected = project_first_run_receipt(_receipt())
    declared = set(get_run_output_schema()["properties"]["first_run_receipt"]["properties"])

    assert projected is not None
    assert set(projected) <= declared
