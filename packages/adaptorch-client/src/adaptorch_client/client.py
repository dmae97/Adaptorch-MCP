"""Synchronous AdaptOrch API client."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Self
from urllib.parse import quote, urlencode

from adaptorch_client.config import ClientConfig
from adaptorch_client.errors import AdaptOrchAPIError
from adaptorch_client.models import CapabilitySet, JSONMapping, JSONValue, Principal, Run
from adaptorch_client.polling import PollPolicy, RunPollResult
from adaptorch_client.polling import wait_for_run as poll_run
from adaptorch_client.provider import ProviderCredential
from adaptorch_client.report import (
    REPORT_FORMATS,
    REPORT_LOCALES,
    RunReport,
    RunReportFormat,
    RunReportLocale,
    parse_run_report,
    report_media_type,
)
from adaptorch_client.responses import (
    NAVIGATION_ALGORITHMS,
    ArtifactListResponse,
    EvidenceNavigation,
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

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close pooled keep-alive connections.

        Later calls still work, each on a new connection that is closed afterwards.
        """
        self._transport.close()

    def capabilities(self) -> CapabilitySet:
        """Return API capabilities."""
        return CapabilitySet.from_payload(
            self._transport.request(RequestSpec("GET", "/v1/capabilities"))
        )

    def whoami(self) -> Principal:
        """Return the authenticated principal."""
        return Principal.from_payload(self._transport.request(RequestSpec("GET", "/v1/whoami")))

    def submit_run(
        self,
        spec: Mapping[str, JSONValue],
        idempotency_key: str,
        *,
        provider_credential: ProviderCredential | None = None,
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
                    provider_credential=provider_credential,
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
        """Return one subject-bound run."""
        return self._get_run(run_id, None)

    def _get_run(self, run_id: str, timeout_seconds: float | None) -> Run:
        return Run.from_payload(
            self._resource(
                RequestSpec(
                    "GET", f"/v1/runs/{self._segment(run_id)}", timeout_seconds=timeout_seconds
                ),
                run_id,
            )
        )

    def wait_for_run(self, run_id: str, *, policy: PollPolicy | None = None) -> RunPollResult:
        """Read until terminal or a polling bound, never resubmit or cancel the run."""
        self._segment(run_id)
        return poll_run(
            lambda remaining: self._get_run(run_id, remaining),
            policy if policy is not None else PollPolicy(),
        )

    def cancel_run(self, run_id: str, reason: str | None = None) -> Run:
        """Cancel one run with an optional reason."""
        payload: dict[str, JSONValue] = {} if reason is None else {"reason": reason}
        return Run.from_payload(
            self._resource(
                RequestSpec(
                    "PUT",
                    f"/v1/runs/{self._segment(run_id)}/cancel",
                    payload=payload,
                ),
                run_id,
            )
        )

    def get_evidence(self, run_id: str) -> EvidenceReport:
        """Return the evidence report for one run."""
        return EvidenceReport.from_payload(
            self._resource(RequestSpec("GET", f"/v1/runs/{self._segment(run_id)}/evidence"), run_id)
        )

    def list_artifacts(self, run_id: str) -> ArtifactListResponse:
        """List artifacts for one run."""
        return ArtifactListResponse.from_payload(
            self._resource(
                RequestSpec("GET", f"/v1/runs/{self._segment(run_id)}/artifacts"), run_id
            )
        )

    def get_run_report(
        self,
        run_id: str,
        *,
        format: RunReportFormat = "json",
        locale: RunReportLocale | None = None,
    ) -> RunReport:
        """Download one saved terminal-run report (JSON or PDF). Read-only, no new run.

        ``locale`` applies to PDF only and defaults to ``en``; translation changes the
        PDF presentation, never the JSON data.
        """
        if format not in REPORT_FORMATS:
            raise ValueError(f"format must be one of {list(REPORT_FORMATS)}")
        if format == "json" and locale is not None:
            raise ValueError("locale applies to the PDF report only")
        if format == "pdf":
            locale = "en" if locale is None else locale
            if locale not in REPORT_LOCALES:
                raise ValueError(f"locale must be one of {list(REPORT_LOCALES)}")
        query = "" if locale is None else f"?{urlencode({'locale': locale})}"
        path = f"/v1/runs/{self._segment(run_id)}/report.{format}{query}"
        content, media_type = self._transport.request_document(
            RequestSpec("GET", path), report_media_type(format)
        )
        return parse_run_report(
            run_id, format, locale, content, media_type, HTTPTransport.decode_mapping
        )

    def navigate_evidence(
        self,
        question: str,
        evidence_pack: Sequence[Mapping[str, JSONValue]],
        *,
        algorithm_version: str = "graph_v5",
    ) -> EvidenceNavigation:
        """Navigate a fixed evidence pack. No model call, no quota, nothing stored."""
        if algorithm_version not in NAVIGATION_ALGORITHMS:
            raise ValueError(f"algorithm_version must be one of {list(NAVIGATION_ALGORITHMS)}")
        payload: dict[str, JSONValue] = {
            "question": question,
            "evidence_pack": [dict(item) for item in evidence_pack],
            "algorithm_version": algorithm_version,
        }
        return EvidenceNavigation.from_payload(
            self._transport.request(RequestSpec("POST", "/v1/navigation/evidence", payload=payload))
        )

    def _resource(self, request: RequestSpec, run_id: str) -> JSONMapping:
        payload = self._transport.request(request)
        if payload.get("run_id") != run_id:
            raise AdaptOrchAPIError("AdaptOrch response belongs to a different run")
        return payload

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
