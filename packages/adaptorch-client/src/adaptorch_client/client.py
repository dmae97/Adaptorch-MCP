"""Synchronous AdaptOrch API client."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import quote, urlencode

from adaptorch_client.config import ClientConfig
from adaptorch_client.models import CapabilitySet, JSONValue, Principal, Run
from adaptorch_client.responses import (
    ArtifactListResponse,
    EvidenceReport,
    RunListResponse,
)
from adaptorch_client.transport import HTTPTransport, RequestSpec

_IDEMPOTENCY_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class AdaptOrchClient:
    """Small synchronous client for the AdaptOrch v1 API."""

    __slots__ = ("_transport",)

    def __init__(self, config: ClientConfig) -> None:
        self._transport = HTTPTransport(config)

    def capabilities(self) -> CapabilitySet:
        """Return API capabilities."""
        return CapabilitySet.from_payload(
            self._transport.request(RequestSpec("GET", "/v1/capabilities"))
        )

    def whoami(self) -> Principal:
        """Return the authenticated principal."""
        return Principal.from_payload(
            self._transport.request(RequestSpec("GET", "/v1/whoami"))
        )

    def submit_run(
        self,
        spec: Mapping[str, JSONValue],
        idempotency_key: str,
    ) -> Run:
        """Submit one run without retrying the POST request."""
        self._require_idempotency_key(idempotency_key)
        return Run.from_payload(
            self._transport.request(
                RequestSpec(
                    "POST",
                    "/v1/runs",
                    payload=spec,
                    headers={"Idempotency-Key": idempotency_key},
                )
            )
        )

    def list_runs(
        self,
        status: str | None = None,
        project_id: str | None = None,
    ) -> RunListResponse:
        """List runs, optionally filtered by status and project."""
        filters: list[tuple[str, str]] = []
        if status is not None:
            filters.append(("status", status))
        if project_id is not None:
            filters.append(("project_id", project_id))
        query = f"?{urlencode(filters)}" if filters else ""
        return RunListResponse.from_payload(
            self._transport.request(RequestSpec("GET", f"/v1/runs{query}"))
        )

    def get_run(self, run_id: str) -> Run:
        """Return one run."""
        return Run.from_payload(
            self._transport.request(RequestSpec("GET", f"/v1/runs/{self._segment(run_id)}"))
        )

    def cancel_run(self, run_id: str, reason: str | None = None) -> Run:
        """Cancel one run with an optional reason."""
        payload: dict[str, JSONValue] = {} if reason is None else {"reason": reason}
        return Run.from_payload(
            self._transport.request(
                RequestSpec(
                    "PUT",
                    f"/v1/runs/{self._segment(run_id)}/cancel",
                    payload=payload,
                )
            )
        )

    def get_evidence(self, run_id: str) -> EvidenceReport:
        """Return the evidence report for one run."""
        return EvidenceReport.from_payload(
            self._transport.request(
                RequestSpec("GET", f"/v1/runs/{self._segment(run_id)}/evidence")
            )
        )

    def list_artifacts(self, run_id: str) -> ArtifactListResponse:
        """List artifacts for one run."""
        return ArtifactListResponse.from_payload(
            self._transport.request(
                RequestSpec("GET", f"/v1/runs/{self._segment(run_id)}/artifacts")
            )
        )

    @staticmethod
    def _segment(value: str) -> str:
        if not value:
            raise ValueError("path segment must not be empty")
        encoded = quote(value, safe="")
        return encoded.replace(".", "%2E") if value in {".", ".."} else encoded

    @staticmethod
    def _require_idempotency_key(value: str) -> None:
        if not _IDEMPOTENCY_KEY_RE.fullmatch(value):
            raise ValueError("idempotency_key must be a hyphenated UUID")
