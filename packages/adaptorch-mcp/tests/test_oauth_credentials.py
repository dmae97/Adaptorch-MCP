from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import request

import pytest
from adaptorch.n8n_connector import ControlPlaneProviderCredential, N8nConnectorConfig, N8nHttpError

from adaptorch_mcp.backend_config import build_parent_config, parent_n8n_connector
from adaptorch_mcp.control_plane_backend import SafeControlPlaneConnector
from adaptorch_mcp.runtime import resolve_provider_credential
from test_control_plane_backend import Wire

_ENV = {
    "ADAPTORCH_MCP_PROVIDER": "openai_codex",
    "ADAPTORCH_MCP_PROVIDER_MODEL": "gpt-5-codex",
    "ADAPTORCH_MCP_PROVIDER_API_KEY": "synthetic-oauth-token",
    "ADAPTORCH_MCP_PROVIDER_AUTH_TYPE": "oauth",
    "ADAPTORCH_MCP_PROVIDER_ACCOUNT_ID": "caller-account",
}


def test_wrapper_preserves_oauth_metadata_in_parent_config() -> None:
    credential = resolve_provider_credential(_ENV)
    config = build_parent_config(
        base_url="https://api.example.test",
        api_token="tenant-key",
        timeout_seconds=10,
        provider_credential=credential,
    )
    parent = config.provider_credential
    assert parent is not None
    assert parent.auth_type == "oauth"
    assert parent.account_id == "caller-account"
    assert parent.resolve_api_key() == "synthetic-oauth-token"
    assert "synthetic-oauth-token" not in repr(credential)
    assert "caller-account" not in repr(credential)


def test_wrapper_rejects_old_engine_instead_of_dropping_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass
    class OldCredential:
        provider: str
        model: str
        api_key: str | None = None

    credential = resolve_provider_credential(_ENV)
    monkeypatch.setattr(parent_n8n_connector, "ControlPlaneProviderCredential", OldCredential)
    with pytest.raises(RuntimeError, match="too old for OAuth"):
        build_parent_config(
            base_url="https://api.example.test",
            api_token="tenant-key",
            timeout_seconds=10,
            provider_credential=credential,
        )


def test_wrapper_keeps_rotating_token_command_on_the_client() -> None:
    env = {k: v for k, v in _ENV.items() if k != "ADAPTORCH_MCP_PROVIDER_API_KEY"}
    env["ADAPTORCH_MCP_PROVIDER_API_KEY_COMMAND"] = "oauth-token-helper"
    credential = resolve_provider_credential(env)
    config = build_parent_config(
        base_url="https://api.example.test",
        api_token="tenant-key",
        timeout_seconds=10,
        provider_credential=credential,
    )
    assert config.provider_credential is not None
    assert config.provider_credential.api_key is None
    assert config.provider_credential.api_key_command == "oauth-token-helper"
    assert config.provider_credential.account_id == "caller-account"


def test_wrapper_rejects_ambiguous_auto_provider_for_oauth() -> None:
    with pytest.raises(ValueError, match="explicit provider"):
        resolve_provider_credential({**_ENV, "ADAPTORCH_MCP_PROVIDER": "auto"})


def test_hardened_transport_forwards_oauth_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    wire = Wire()
    wire.replies = [(201, b'{"run_id":"oauth-run"}')]
    monkeypatch.setattr(request.HTTPSHandler, "https_open", lambda _, req: wire.open(req))
    config = build_parent_config(
        base_url="https://control.invalid",
        api_token="ado_tenant",
        timeout_seconds=10,
        provider_credential=resolve_provider_credential(_ENV),
    )
    client = SafeControlPlaneConnector(config)
    client.run_task(payload={"subtasks": [{"id": "one", "description": "reply"}]})
    assert wire.calls[0].get_header("X-provider-auth-type") == "oauth"
    assert wire.calls[0].get_header("X-provider-account-id") == "caller-account"


def test_hardened_transport_never_refreshes_again_to_redact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def token(command: str) -> str:
        calls.append(command)
        return f"rotating-token-{len(calls)}"

    monkeypatch.setattr(parent_n8n_connector, "_run_api_key_command", token)
    wire = Wire()
    wire.replies = [(401, json.dumps({"detail": "rejected rotating-token-1"}).encode())]
    monkeypatch.setattr(request.HTTPSHandler, "https_open", lambda _, req: wire.open(req))
    client = SafeControlPlaneConnector(
        N8nConnectorConfig(
            base_url="https://control.invalid",
            api_token="ado_tenant",
            provider_credential=ControlPlaneProviderCredential(
                "openai_codex",
                "gpt-5-codex",
                api_key_command="oauth-helper",
                auth_type="oauth",
                account_id="caller-account",
            ),
        )
    )
    with pytest.raises(N8nHttpError) as error:
        client.run_task(payload={"subtasks": [{"id": "one", "description": "reply"}]})
    assert "rotating-token-1" not in str(error.value)
    assert calls == ["oauth-helper"]
