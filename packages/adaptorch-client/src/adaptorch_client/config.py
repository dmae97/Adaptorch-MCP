"""Validated client configuration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_UNSAFE_URL_CHARACTERS = frozenset({"\\", "?", "#"})


def validate_api_url(api_url: str) -> str:
    """Validate an AdaptOrch API base URL and return it without a trailing slash.

    Raise ``ValueError`` for surrounding whitespace, control characters,
    backslashes, embedded credentials, a path, query, or fragment, port 0,
    a missing host, or plain HTTP on a non-loopback host.
    """
    if api_url != api_url.strip() or any(
        character in _UNSAFE_URL_CHARACTERS or ord(character) < 32 or ord(character) == 127
        for character in api_url
    ):
        raise ValueError("api_url contains unsafe characters")

    try:
        parsed = urlsplit(api_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("api_url is invalid") from error

    if hostname is None or not parsed.netloc:
        raise ValueError("api_url must include a host")
    if port == 0:
        raise ValueError("api_url port must be positive")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("api_url must not include credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("api_url must not include a path, query, or fragment")
    if parsed.scheme == "http" and hostname not in _LOOPBACK_HOSTS:
        raise ValueError("HTTP is allowed only for exact loopback hosts")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("api_url must use HTTPS or loopback HTTP")
    return api_url.rstrip("/")


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Connection settings for the AdaptOrch API."""

    api_url: str
    api_key: str = field(repr=False)
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "api_url", validate_api_url(self.api_url))
        if not self.api_key.strip() or any(
            ord(character) < 32 or ord(character) == 127 or ord(character) > 255
            for character in self.api_key
        ):
            raise ValueError("api_key must be a non-empty HTTP header value")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")

    @property
    def auth_headers(self) -> Mapping[str, str]:
        """Return the sole authentication header valid for this credential."""
        if self.api_key.startswith("ado_"):
            return {"X-API-Key": self.api_key}
        return {"Authorization": f"Bearer {self.api_key}"}
