from __future__ import annotations

import pytest

from adaptorch_client import (
    EvidenceReport,
    JSONMapping,
    Run,
    RunListResponse,
    VerificationDiagnostic,
)


def _diagnostic() -> JSONMapping:
    return {"code": "ENV_DEPENDENCY_MISSING", "source": "project_report", "scope": "child_tool"}


def test_typed_observations_and_serialization_preserve_old_and_additive_contracts() -> None:
    payload: JSONMapping = {
        "run_id": "r", "status": "FAILED", "future_field": "retained",
        "verification_diagnostics": [_diagnostic()],
        "verification_diagnostics_schema_version": "verification.diagnostics/v1",
    }
    parsed = Run.from_payload(payload)
    assert parsed.verification_diagnostics == (
        VerificationDiagnostic("ENV_DEPENDENCY_MISSING", "project_report", "child_tool"),
    )
    assert parsed.to_payload() == payload
    payload["verification_diagnostics"] = []
    assert parsed.to_payload()["verification_diagnostics"] == [_diagnostic()]
    assert Run.from_payload({"run_id": "r", "status": "FAILED"}).verification_diagnostics is None
    report = EvidenceReport.from_payload({
        "run_id": "r", "checks": [{"name": "c", "status": "FAILED"}],
        "verification_diagnostics": [_diagnostic()],
        "verification_diagnostics_schema_version": "verification.diagnostics/v1",
    })
    assert report.verification_diagnostics == parsed.verification_diagnostics
    assert report.checks[0].status == "FAILED"


@pytest.mark.parametrize("value", [
    None, {}, [None], [_diagnostic() for _ in range(17)],
    [{"code": "PASS", "source": "project_report", "scope": "child_tool"}],
    [{"code": "ENV_DEPENDENCY_MISSING", "source": "process_spawn", "scope": "child_tool"}],
    [{"code": "PDF_TOOL_EXECUTION_FAILED", "source": "process_spawn",
      "scope": "verification_command"}],
    [{**_diagnostic(), "path": "/synthetic/private", "secret": "test-secret"}],
    [{**_diagnostic(), "tool": "/usr/bin/pdftotext"}],
    [{**_diagnostic(), "tool": ["pdftotext"]}],
])
def test_malformed_observations_drop_only_optional_metadata(value: object) -> None:
    record: JSONMapping = {
        "run_id": "r", "status": "FAILED",
        "verification_diagnostics_schema_version": "verification.diagnostics/v1",
        "verification_diagnostics": value,  # type: ignore[dict-item]
    }
    run = Run.from_payload(record)
    assert run.verification_diagnostics is None
    assert run.to_payload() == {"run_id": "r", "status": "FAILED"}
    report = EvidenceReport.from_payload({**record, "checks": []})
    assert report.verification_diagnostics is None
    assert report.to_payload() == {"run_id": "r", "status": "FAILED", "checks": []}


@pytest.mark.parametrize("version", [None, 1, [], "verification.diagnostics/v2"])
def test_unknown_versions_cannot_reexport_optional_metadata(version: object) -> None:
    run = Run.from_payload({
        "run_id": "r", "status": "SUCCEEDED", "unknown_extension": "retained",
        "verification_diagnostics": [_diagnostic()],
        "verification_diagnostics_schema_version": version,  # type: ignore[dict-item]
    })
    assert run.verification_diagnostics is None
    assert run.to_payload() == {
        "run_id": "r", "status": "SUCCEEDED", "unknown_extension": "retained"
    }


def test_run_list_serialization_normalizes_nested_diagnostics_and_keeps_pagination() -> None:
    record: JSONMapping = {
        "items": [{
            "run_id": "r", "status": "FAILED", "unknown_run_field": "retained",
            "verification_diagnostics_schema_version": "verification.diagnostics/v1",
            "verification_diagnostics": [{**_diagnostic(), "secret": "synthetic-secret"}],
        }],
        "next_cursor": "next", "unknown_page_field": "retained",
    }
    page = RunListResponse.from_payload(record)
    assert page.items[0].verification_diagnostics is None
    assert page.to_payload() == {
        "items": [{"run_id": "r", "status": "FAILED", "unknown_run_field": "retained"}],
        "next_cursor": "next", "unknown_page_field": "retained",
    }
