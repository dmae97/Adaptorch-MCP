"""Validate wrapper connection settings and construct the installed engine's config."""

from __future__ import annotations

from collections.abc import Mapping
from threading import TIMEOUT_MAX
from typing import Any, Protocol

import adaptorch.n8n_connector as parent_n8n_connector
from adaptorch.n8n_connector import N8nConnectorConfig, N8nRetryPolicy

__all__ = [
    "ProviderCredentialConfig",
    "build_parent_config",
    "parent_n8n_connector",
    "valid_wait_controls",
]


def valid_wait_controls(arguments: Mapping[str, Any]) -> bool:
    for name in ("timeout_seconds", "poll_interval_seconds"):
        value = arguments.get(name)
        if value is not None and (type(value) not in (int, float) or not 0 < value <= TIMEOUT_MAX):
            return False
    return True


class ProviderCredentialConfig(Protocol):
    @property
    def provider(self) -> str:
        raise NotImplementedError

    @property
    def model(self) -> str:
        raise NotImplementedError

    @property
    def api_key(self) -> str | None:
        raise NotImplementedError


def build_parent_config(
    *,
    base_url: str,
    api_token: str,
    timeout_seconds: float,
    provider_credential: ProviderCredentialConfig | None,
) -> N8nConnectorConfig:
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= TIMEOUT_MAX:
        raise ValueError("timeout_seconds must be positive and within the platform wait limit")
    config_kwargs: dict[str, Any] = {
        "base_url": base_url,
        "api_token": api_token.strip(),
        "timeout_seconds": timeout_seconds,
        "retry_policy": N8nRetryPolicy(max_attempts=1),
    }
    if provider_credential is not None:
        credential_type = getattr(parent_n8n_connector, "ControlPlaneProviderCredential", None)
        config_fields = getattr(N8nConnectorConfig, "__dataclass_fields__", {})
        if credential_type is None or "provider_credential" not in config_fields:
            raise RuntimeError(
                "installed adaptorch engine is too old for MCP provider credentials; "
                "install an engine revision with ControlPlaneProviderCredential support"
            )
        config_kwargs["provider_credential"] = credential_type(
            provider=provider_credential.provider,
            model=provider_credential.model,
            api_key=provider_credential.api_key,
        )
    return N8nConnectorConfig(**config_kwargs)
