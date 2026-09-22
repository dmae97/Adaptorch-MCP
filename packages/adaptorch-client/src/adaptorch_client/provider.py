"""Explicit request-scoped provider credentials and safe error text."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

_MAX_HEADER_LENGTH: Final = 4096


def _valid_header(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= _MAX_HEADER_LENGTH
        and value == value.strip()
        and all(char.isprintable() and ord(char) <= 255 for char in value)
    )


@dataclass(frozen=True, slots=True)
class ProviderCredential:
    """BYOK headers for one run submission, never discovered from the environment.

    Values must be nonblank printable Latin-1 text of at most 4096 bytes,
    without surrounding whitespace. Values are never normalized.
    ``api_key`` and ``account_id`` are excluded from the representation; do not
    put secrets in ``provider`` or ``model``. OAuth is supported for openai_codex.
    """

    provider: str
    model: str
    api_key: str = field(repr=False)
    auth_type: str | None = None
    account_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("provider", self.provider),
            ("model", self.model),
            ("api_key", self.api_key),
        ):
            if not _valid_header(value):
                raise ValueError(
                    f"{name} must be a safe nonblank HTTP header value (max 4096 bytes)"
                )
        kind = self.auth_type
        if kind is None:
            kind = "oauth" if self.provider.lower() == "openai_codex" else "api_key"
        if not _valid_header(kind) or kind not in {"api_key", "oauth"}:
            raise ValueError("provider_auth_type_invalid")
        if kind == "oauth" and self.provider.lower() != "openai_codex":
            raise ValueError("provider_oauth_unsupported")
        if self.account_id is not None:
            if not _valid_header(self.account_id) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,256}", self.account_id
            ):
                raise ValueError("provider_account_id_invalid")
            if kind != "oauth":
                raise ValueError("provider_account_requires_oauth")
        if kind == "oauth" and not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", self.api_key):
            raise ValueError("provider_oauth_token_invalid")
        object.__setattr__(self, "auth_type", kind)

    @property
    def headers(self) -> Mapping[str, str]:
        """Compatibility view; transport forwards it only on run submission."""
        result = {
            "X-Provider": self.provider,
            "X-Provider-Model": self.model,
            "X-Provider-Key": self.api_key,
        }
        if self.auth_type == "oauth":
            result["X-Provider-Auth-Type"] = "oauth"
        if self.account_id is not None:
            result["X-Provider-Account-Id"] = self.account_id
        return result


def sanitize_error(value: str, secrets: tuple[str, ...], limit: int) -> str:
    """Redact exact credentials before removing controls and truncating."""
    ordered_secrets = sorted(set(secrets), key=len, reverse=True)
    redacted = value
    for secret in ordered_secrets:
        redacted = redacted.replace(secret, "[redacted]")
    printable = "".join(char if char.isprintable() else " " for char in redacted)
    # Replacing controls with spaces must not reconstruct a printable credential.
    for secret in ordered_secrets:
        printable = printable.replace(secret, "[redacted]")
    return printable[:limit]
