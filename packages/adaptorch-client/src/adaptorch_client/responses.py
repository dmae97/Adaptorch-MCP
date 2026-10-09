"""Typed direct list and report responses for the v1 public API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Self

from adaptorch_client.models import (
    Artifact,
    EvidenceCheck,
    JSONValue,
    PayloadResult,
    Run,
    VerificationDiagnostic,
    contract_error,
    optional_string_at,
    require_array,
    require_object,
    stored_copy,
    string_at,
    verification_diagnostics_at,
)


@dataclass(frozen=True, slots=True)
class RunListResponse(PayloadResult):
    """Direct ``GET /v1/runs`` page: ``items`` plus optional ``next_cursor``."""

    items: tuple[Run, ...]
    next_cursor: str | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, JSONValue]) -> Self:
        """Validate one raw run page against the v1 contract."""
        record = stored_copy(payload)
        items = require_array(record.get("items"), "items")
        parsed_items = tuple(
            Run.parse_at(item, f"items[{index}]") for index, item in enumerate(items)
        )
        record["items"] = [item.to_payload() for item in parsed_items]
        return cls(
            record,
            items=parsed_items,
            next_cursor=optional_string_at(record, "next_cursor", ""),
        )


@dataclass(frozen=True, slots=True)
class EvidenceReport(PayloadResult):
    """Direct ``GET /v1/runs/{run_id}/evidence`` report: ``run_id`` plus ``checks``."""

    run_id: str
    checks: tuple[EvidenceCheck, ...]
    verification_diagnostics: tuple[VerificationDiagnostic, ...] | None = None
    verification_diagnostics_schema_version: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, JSONValue]) -> Self:
        """Validate one raw evidence report against the v1 contract."""
        record = stored_copy(payload)
        checks = require_array(record.get("checks"), "checks")
        verification_diagnostics = verification_diagnostics_at(record, "")
        return cls(
            record,
            run_id=string_at(record, "run_id", ""),
            checks=tuple(
                EvidenceCheck.parse_at(check, f"checks[{index}]")
                for index, check in enumerate(checks)
            ),
            verification_diagnostics=verification_diagnostics,
            verification_diagnostics_schema_version=optional_string_at(
                record, "verification_diagnostics_schema_version", ""
            ),
        )


@dataclass(frozen=True, slots=True)
class ArtifactListResponse(PayloadResult):
    """Structured v1 items or a control-plane reference map; neither is fetched automatically."""

    run_id: str
    items: tuple[Artifact, ...]
    artifact_urls: Mapping[str, str] | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, JSONValue]) -> Self:
        """Validate one raw artifact listing against the v1 contract."""
        record = stored_copy(payload)
        if "artifacts" in record:
            if "items" in record:
                raise contract_error("artifacts", "a single unambiguous representation")
            references: dict[str, str] = {}
            for name, target in require_object(record["artifacts"], "artifacts").items():
                if not isinstance(target, str):
                    raise contract_error("artifacts", "a string reference map")
                references[name] = target
            return cls(
                record,
                run_id=string_at(record, "run_id", ""),
                items=tuple(
                    Artifact.parse_at({"artifact_id": name, "name": name}, f"artifacts.{name}")
                    for name in references
                ),
                artifact_urls=MappingProxyType(references),
            )
        items = require_array(record.get("items"), "items")
        return cls(
            record,
            run_id=string_at(record, "run_id", ""),
            items=tuple(
                Artifact.parse_at(item, f"items[{index}]") for index, item in enumerate(items)
            ),
        )
