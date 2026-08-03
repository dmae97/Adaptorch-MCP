# mypy: disable-error-code="import-not-found"
# pyright: reportMissingImports=false
from __future__ import annotations

from typing import Any

import pytest

from adaptorch_mcp import hardening, runtime


def test_provider_credential_env_is_all_or_none_and_secret_safe() -> None:
    assert runtime.resolve_provider_credential({}) is None

    credential = runtime.resolve_provider_credential(
        {
            "ADAPTORCH_MCP_PROVIDER": " OpenAI ",
            "ADAPTORCH_MCP_PROVIDER_MODEL": " gpt-4.1-mini ",
            "ADAPTORCH_MCP_PROVIDER_API_KEY": " provider-secret-value ",
        }
    )

    assert credential is not None
    assert credential.provider == "openai"
    assert credential.model == "gpt-4.1-mini"
    assert credential.api_key == "provider-secret-value"
    assert "provider-secret-value" not in repr(credential)

    with pytest.raises(ValueError, match="must be set together"):
        runtime.resolve_provider_credential({"ADAPTORCH_MCP_PROVIDER": "openai"})


def test_runtime_passes_process_local_provider_credential_to_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_build(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runtime, "build_hardened_mcp_server", fake_build)
    monkeypatch.setattr(runtime, "serve_stdio", lambda *_args, **_kwargs: 0)

    result = runtime.run_hardened_main(
        ["--transport", "stdio", "--base-url", "https://adaptorch.com"],
        env={
            "ADAPTORCH_CONTROL_PLANE_TOKEN": "tenant-token",
            "ADAPTORCH_MCP_PROVIDER": "openai",
            "ADAPTORCH_MCP_PROVIDER_MODEL": "gpt-4.1-mini",
            "ADAPTORCH_MCP_PROVIDER_API_KEY": "provider-secret-value",
        },
    )

    assert result == 0
    credential = captured["provider_credential"]
    assert credential.provider == "openai"
    assert credential.model == "gpt-4.1-mini"
    assert credential.api_key == "provider-secret-value"
    assert "provider-secret-value" not in repr(captured)


def test_parent_connector_receives_provider_credential_without_schema_exposure() -> None:
    if not hasattr(hardening.parent_n8n_connector, "ControlPlaneProviderCredential"):
        pytest.skip("installed engine predates provider-credential forwarding")

    wrapper_credential = runtime.ProviderCredentialConfig(
        provider="openai",
        model="gpt-4.1-mini",
        api_key="provider-secret-value",
    )

    config = hardening._parent_connector_config(
        base_url="https://adaptorch.com",
        api_token="tenant-token",
        timeout_seconds=10.0,
        provider_credential=wrapper_credential,
    )

    assert config.provider_credential is not None
    assert config.provider_credential.provider == "openai"
    assert config.provider_credential.model == "gpt-4.1-mini"
    assert config.provider_credential.api_key == "provider-secret-value"
    assert "provider-secret-value" not in repr(config.provider_credential)


def test_byok_fails_closed_when_installed_engine_is_too_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(
        hardening.parent_n8n_connector,
        "ControlPlaneProviderCredential",
        raising=False,
    )

    with pytest.raises(RuntimeError, match="too old for MCP provider credentials"):
        hardening._parent_connector_config(
            base_url="https://adaptorch.com",
            api_token="tenant-token",
            timeout_seconds=10.0,
            provider_credential=runtime.ProviderCredentialConfig(
                provider="openai",
                model="gpt-4.1-mini",
                api_key="provider-secret-value",
            ),
        )
