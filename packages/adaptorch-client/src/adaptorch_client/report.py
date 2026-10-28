"""Saved run report downloads: the server's exact bytes plus minimal binding checks."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from adaptorch_client.errors import AdaptOrchAPIError
from adaptorch_client.models import JSONMapping

RunReportFormat = Literal["json", "pdf"]
RunReportLocale = Literal["en", "ko", "zh-CN"]
REPORT_FORMATS: tuple[RunReportFormat, ...] = ("json", "pdf")
REPORT_LOCALES: tuple[RunReportLocale, ...] = ("en", "ko", "zh-CN")
_MEDIA_TYPES: dict[RunReportFormat, str] = {"json": "application/json", "pdf": "application/pdf"}
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class RunReport:
    """One saved terminal-run report, as served (``adaptorch-run-report.v1`` today).

    ``content`` is never re-encoded, so a JSON download stays byte-identical to the
    ``run-report.json`` the PDF embeds. The report shows the saved final output; it is
    not a correctness verdict. PDF bytes are checked for a PDF signature only.
    """

    run_id: str
    format: RunReportFormat
    locale: RunReportLocale | None
    media_type: str
    snapshot_sha256: str | None
    content: bytes = field(repr=False)

    @property
    def sha256(self) -> str:
        """SHA-256 of the downloaded bytes (not the report's own snapshot hash)."""
        return hashlib.sha256(self.content).hexdigest()

    def to_payload(self) -> JSONMapping:
        """Describe the download without its content."""
        return {
            "run_id": self.run_id,
            "format": self.format,
            "locale": self.locale,
            "media_type": self.media_type,
            "bytes": len(self.content),
            "sha256": self.sha256,
            "snapshot_sha256": self.snapshot_sha256,
        }


def report_media_type(report_format: RunReportFormat) -> str:
    return _MEDIA_TYPES[report_format]


def parse_run_report(
    run_id: str,
    report_format: RunReportFormat,
    locale: RunReportLocale | None,
    content: bytes,
    media_type: str,
    decode: Callable[[bytes], JSONMapping],
) -> RunReport:
    """Fail closed unless the body is the requested kind and, for JSON, this run's report."""
    expected = _MEDIA_TYPES[report_format]
    if media_type != expected:
        raise AdaptOrchAPIError(f"AdaptOrch report was not served as {expected}")
    snapshot: str | None = None
    if report_format == "pdf":
        if not content.startswith(b"%PDF-"):
            raise AdaptOrchAPIError("AdaptOrch report is not a PDF document")
    else:
        report = decode(content)
        run = report.get("run")
        if not isinstance(run, dict) or run.get("run_id") != run_id:
            raise AdaptOrchAPIError("AdaptOrch report belongs to a different run")
        value = report.get("snapshot_sha256")
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise AdaptOrchAPIError("AdaptOrch report has no valid snapshot_sha256")
        snapshot = value
    return RunReport(run_id, report_format, locale, media_type, snapshot, content)
