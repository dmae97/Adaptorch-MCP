# mypy: disable-error-code="import-not-found"
# pyright: reportMissingImports=false
from __future__ import annotations

from typing import Any

import pytest
from adaptorch.providers import DEFAULT_API_KEY_ENV

from adaptorch_mcp import hardening, runtime

_EVERY_KEY_ENV = tuple(sorted(DEFAULT_API_KEY_ENV.values()))


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


class TestAutoProvider:
    """``ADAPTORCH_MCP_PROVIDER=auto`` discovers the tenant's own key on the tenant's machine.

    Same rule as the engine's ``ADAPTORCH_EXECUTION_PROVIDER=auto`` (exactly one
    provider key present), applied to the wrapper's process environment instead
    of the operator's. The provider list is the engine's ``DEFAULT_API_KEY_ENV``,
    never a retyped copy.
    """

    def test_exactly_one_provider_key_resolves_provider_model_and_key(self) -> None:
        credential = runtime.resolve_provider_credential(
            {
                "ADAPTORCH_MCP_PROVIDER": " Auto ",
                "ADAPTORCH_MCP_PROVIDER_MODEL": "claude-sonnet-4-5",
                "ANTHROPIC_API_KEY": " anthropic-secret-value ",
            }
        )

        assert credential is not None
        assert credential.provider == "anthropic"
        assert credential.model == "claude-sonnet-4-5"
        assert credential.api_key == "anthropic-secret-value"
        assert "anthropic-secret-value" not in repr(credential)

    def test_an_empty_key_variable_does_not_count(self) -> None:
        credential = runtime.resolve_provider_credential(
            {
                "ADAPTORCH_MCP_PROVIDER": "auto",
                "ADAPTORCH_MCP_PROVIDER_MODEL": "gpt-4.1-mini",
                "OPENAI_API_KEY": "openai-secret-value",
                "GROQ_API_KEY": "   ",
            }
        )

        assert credential is not None
        assert credential.provider == "openai"

    def test_no_provider_key_fails_closed_naming_every_variable_checked(self) -> None:
        with pytest.raises(ValueError, match="found no provider key") as excinfo:
            runtime.resolve_provider_credential(
                {
                    "ADAPTORCH_MCP_PROVIDER": "auto",
                    "ADAPTORCH_MCP_PROVIDER_MODEL": "gpt-4.1-mini",
                }
            )
        for key_env in _EVERY_KEY_ENV:
            assert key_env in str(excinfo.value)

    def test_two_provider_keys_fail_closed_naming_both(self) -> None:
        with pytest.raises(ValueError, match="ambiguous") as excinfo:
            runtime.resolve_provider_credential(
                {
                    "ADAPTORCH_MCP_PROVIDER": "auto",
                    "ADAPTORCH_MCP_PROVIDER_MODEL": "gpt-4.1-mini",
                    "OPENAI_API_KEY": "openai-secret-value",
                    "ANTHROPIC_API_KEY": "anthropic-secret-value",
                }
            )
        message = str(excinfo.value)
        assert "OPENAI_API_KEY" in message
        assert "ANTHROPIC_API_KEY" in message
        assert "GROQ_API_KEY" not in message
        assert "secret-value" not in message

    def test_an_explicit_wrapper_key_alongside_auto_is_refused(self) -> None:
        with pytest.raises(ValueError, match="name the provider"):
            runtime.resolve_provider_credential(
                {
                    "ADAPTORCH_MCP_PROVIDER": "auto",
                    "ADAPTORCH_MCP_PROVIDER_MODEL": "gpt-4.1-mini",
                    "ADAPTORCH_MCP_PROVIDER_API_KEY": "which-provider-is-this",
                    "OPENAI_API_KEY": "openai-secret-value",
                }
            )

    def test_auto_still_requires_a_model(self) -> None:
        with pytest.raises(ValueError, match="must be set together"):
            runtime.resolve_provider_credential(
                {"ADAPTORCH_MCP_PROVIDER": "auto", "OPENAI_API_KEY": "openai-secret-value"}
            )

    def test_the_provider_list_is_the_engine_constant(self) -> None:
        assert runtime.auto_provider_key_envs() == _EVERY_KEY_ENV

    def test_runtime_forwards_the_discovered_credential_to_the_parent(
        self, monkeypatch: pytest.MonkeyPatch
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
                "ADAPTORCH_MCP_PROVIDER": "auto",
                "ADAPTORCH_MCP_PROVIDER_MODEL": "llama-3.3-70b-versatile",
                "GROQ_API_KEY": "groq-secret-value",
            },
        )

        assert result == 0
        credential = captured["provider_credential"]
        assert credential.provider == "groq"
        assert credential.model == "llama-3.3-70b-versatile"
        assert credential.api_key == "groq-secret-value"
        assert "groq-secret-value" not in repr(captured)


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
