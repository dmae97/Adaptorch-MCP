"""Process-local, explicit hosted credentials. No provider auto-discovery or storage."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from adaptorch_client.config import ClientConfig
from adaptorch_client.provider import ProviderCredential

MAX_TIMEOUT_SECONDS = 300.0
_UNSUPPORTED_ENV = (
    "ADAPTORCH_MCP_PROVIDER_API_KEY_COMMAND",
    "ADAPTORCH_MCP_PROVIDER_FALLBACK",
    "ADAPTORCH_MCP_PROVIDER_FALLBACK_MODEL",
    "ADAPTORCH_MCP_PROVIDER_FALLBACK_API_KEY",
    "ADAPTORCH_MCP_PROVIDER_FALLBACK_API_KEY_COMMAND",
    "ADAPTORCH_MCP_ALLOW_INSECURE_CONTROL_PLANE",
    "ADAPTORCH_MCP_HTTP_TOKEN",
)


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    client: ClientConfig = field(repr=False)
    provider: ProviderCredential | None = field(default=None, repr=False)
    allow_loopback_http: bool = False

    def __post_init__(self) -> None:
        parsed = urlsplit(self.client.api_url)
        if (
            not parsed.netloc.isascii()
            or "%" in parsed.netloc
            or any(char.isspace() for char in parsed.netloc)
        ):
            raise ValueError("origin must have a plain ASCII hostname without escaped delimiters")
        if parsed.scheme != "https" and not self.allow_loopback_http:
            raise ValueError("HTTPS required; loopback HTTP requires --allow-loopback-http")
        token = self.client.api_key
        if len(token) > 4096 or token != token.strip():
            raise ValueError("tenant key must be a bounded header without surrounding whitespace")
        if not math.isfinite(self.client.timeout_seconds) or not (
            0 < self.client.timeout_seconds <= MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("request timeout must be finite and within (0, 300] seconds")

    @property
    def secrets(self) -> tuple[str, ...]:
        values = [self.client.api_key]
        if self.provider is not None:
            values.append(self.provider.api_key)
            if self.provider.account_id:
                values.append(self.provider.account_id)
        return tuple(values)


def from_environment(
    env: Mapping[str, str],
    *,
    base_url: str | None = None,
    timeout_seconds: float = 30.0,
    allow_loopback_http: bool = False,
) -> BridgeConfig:
    if env.get("ADAPTORCH_MCP_EXPOSURE_PROFILE", "remote").strip().lower() != "remote":
        raise ValueError("0.6 is remote-only; full/local-engine require a separate private runtime")
    if env.get("ADAPTORCH_MCP_TRANSPORT", "stdio").strip().lower() != "stdio":
        raise ValueError("0.6 is stdio-only; local HTTP is unsupported")
    if any(env.get(name) for name in _UNSUPPORTED_ENV) or any(
        value for name, value in env.items() if name.startswith("ADAPTORCH_MCP_FALLBACK_")
    ):
        raise ValueError("legacy HTTP, key-command, insecure or fallback settings are unsupported")
    provider_fields = {
        "provider": env.get("ADAPTORCH_MCP_PROVIDER"),
        "model": env.get("ADAPTORCH_MCP_PROVIDER_MODEL"),
        "api_key": env.get("ADAPTORCH_MCP_PROVIDER_API_KEY"),
        "auth_type": env.get("ADAPTORCH_MCP_PROVIDER_AUTH_TYPE"),
        "account_id": env.get("ADAPTORCH_MCP_PROVIDER_ACCOUNT_ID"),
    }
    provider = None
    if any(value is not None for value in provider_fields.values()):
        if not all(provider_fields[key] for key in ("provider", "model", "api_key")):
            raise ValueError(
                "explicit provider, model and key are required; keyless is unsupported"
            )
        if provider_fields["provider"] == "auto":
            raise ValueError("provider auto-discovery is unsupported; set an explicit provider")
        provider = ProviderCredential(
            provider=str(provider_fields["provider"]),
            model=str(provider_fields["model"]),
            api_key=str(provider_fields["api_key"]),
            auth_type=provider_fields["auth_type"],
            account_id=provider_fields["account_id"],
        )
    # Deliberate compatibility precedence; never inspect OPENAI_API_KEY or other ambient keys.
    token = env.get("ADAPTORCH_CONTROL_PLANE_TOKEN") or env.get("ADAPTORCH_API_KEY", "")
    origin = (
        base_url
        or env.get("ADAPTORCH_CONTROL_PLANE_BASE_URL", "").strip()
        or "https://adaptorch.com"
    )
    return BridgeConfig(ClientConfig(origin, token, timeout_seconds), provider, allow_loopback_http)
