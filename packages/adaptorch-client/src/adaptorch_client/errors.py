"""Sanitized public client errors."""

from __future__ import annotations


class AdaptOrchAPIError(RuntimeError):
    """A sanitized API, transport, or response failure."""

    __slots__ = ("code", "status_code")

    code: str | None
    status_code: int | None

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
