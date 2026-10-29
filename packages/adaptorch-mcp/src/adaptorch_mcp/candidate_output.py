"""Closed provider-free verification report. No private engine dependency."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

DIGEST_FIELDS = frozenset({
    "verification_id", "candidate_sha256", "subject_sha256", "verifier_bundle_sha256",
    "profile_sha256", "environment_sha256", "parameters_sha256", "report_sha256",
})
TEXT_FIELDS = frozenset({
    "schema_version", "repository_id", "revision", "base_revision", "verifier_id",
    "verifier_version", "status", "outcome", "harness_isolation", "network", "generation_identity",
})


def project_verification_report(value: Mapping[str, Any]) -> dict[str, Any] | None:
    if value.get("schema_version") != "candidate-verification/v1":
        return None
    for key in DIGEST_FIELDS:
        item = value.get(key)
        if not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None:
            return None
    for key in TEXT_FIELDS:
        item = value.get(key)
        if not isinstance(item, str) or not 0 < len(item) <= 128 or not item.isprintable():
            return None
    for key in ("revision", "base_revision"):
        if re.fullmatch(r"[0-9a-f]{40}", value[key]) is None:
            return None
    if value["status"] not in {"RUNNING", "COMPLETED"}:
        return None
    outcome = value["outcome"]
    if outcome not in {"NOT_RUN", "PASS", "FAIL", "ENV_ERROR", "TIMEOUT", "INCONCLUSIVE"}:
        return None
    if (value["status"] == "RUNNING") != (outcome == "NOT_RUN"):
        return None
    if type(value.get("provider_calls")) is not int or value["provider_calls"] != 0:
        return None
    for key in ("model_fallback", "correctness_proof", "release_authorized"):
        if value.get(key) is not False:
            return None
    if (value["harness_isolation"], value["network"], value["generation_identity"]) != (
        "in_process", "unshared", "unknown",
    ):
        return None
    checks = value.get("required_checks")
    if not isinstance(checks, list) or not 1 <= len(checks) <= 256 or not all(
        isinstance(item, str) and 0 < len(item) <= 512 and item.isprintable() for item in checks
    ):
        return None
    attempt = value.get("attempt_id")
    if value["status"] == "COMPLETED" and (
        not isinstance(attempt, str) or not 0 < len(attempt) <= 128 or not attempt.isprintable()
    ):
        return None
    if value["status"] == "RUNNING" and attempt is not None:
        return None
    return {**{key: value[key] for key in DIGEST_FIELDS | TEXT_FIELDS},
            "provider_calls": 0, "model_fallback": False, "correctness_proof": False,
            "release_authorized": False, "required_checks": list(checks), "attempt_id": attempt}
