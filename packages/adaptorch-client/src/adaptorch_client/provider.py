"""Explicit request-scoped provider credentials and safe error text."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

_MAX_HEADER_LENGTH: Final = 4096


@dataclass(frozen=True, slots=True)
class ProviderCredential:
    """BYOK headers for one run submission, never discovered from the environment.

    Values must be nonblank printable Latin-1 text of at most 4096 bytes,
    without surrounding whitespace. Values are never normalized.
    Only ``api_key`` is excluded from the representation; do not put secrets in
    ``provider`` or ``model``.
    """

    provider: str
    model: str
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("provider", self.provider),
            ("model", self.model),
            ("api_key", self.api_key),
        ):
            if (
                not isinstance(value, str)
                or not value
                or len(value) > _MAX_HEADER_LENGTH
                or value != value.strip()
                or any(not char.isprintable() or ord(char) > 255 for char in value)
            ):
                raise ValueError(
                    f"{name} must be a safe nonblank HTTP header value (max 4096 bytes)"
                )

    @property
    def headers(self) -> Mapping[str, str]:
        """Compatibility view; transport forwards it only on run submission."""
        return {
            "X-Provider": self.provider,
            "X-Provider-Model": self.model,
            "X-Provider-Key": self.api_key,
        }


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
