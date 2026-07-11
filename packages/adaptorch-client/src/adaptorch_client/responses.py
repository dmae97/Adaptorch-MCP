"""Typed direct list and report responses for the v1 public API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from adaptorch_client.models import (
    Artifact,
    EvidenceCheck,
    JSONValue,
    PayloadResult,
    Run,
    optional_string_at,
    require_array,
    stored_copy,
    string_at,
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
        return cls(
            record,
            items=tuple(Run.parse_at(item, f"items[{index}]") for index, item in enumerate(items)),
            next_cursor=optional_string_at(record, "next_cursor", ""),
        )


@dataclass(frozen=True, slots=True)
class EvidenceReport(PayloadResult):
    """Direct ``GET /v1/runs/{run_id}/evidence`` report: ``run_id`` plus ``checks``."""

    run_id: str
    checks: tuple[EvidenceCheck, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, JSONValue]) -> Self:
        """Validate one raw evidence report against the v1 contract."""
        record = stored_copy(payload)
        checks = require_array(record.get("checks"), "checks")
        return cls(
            record,
            run_id=string_at(record, "run_id", ""),
            checks=tuple(
                EvidenceCheck.parse_at(check, f"checks[{index}]")
                for index, check in enumerate(checks)
            ),
        )


@dataclass(frozen=True, slots=True)
class ArtifactListResponse(PayloadResult):
    """Direct ``GET /v1/runs/{run_id}/artifacts`` listing: ``run_id`` plus ``items``."""

    run_id: str
    items: tuple[Artifact, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, JSONValue]) -> Self:
        """Validate one raw artifact listing against the v1 contract."""
        record = stored_copy(payload)
        items = require_array(record.get("items"), "items")
        return cls(
            record,
            run_id=string_at(record, "run_id", ""),
            items=tuple(
                Artifact.parse_at(item, f"items[{index}]") for index, item in enumerate(items)
            ),
        )
