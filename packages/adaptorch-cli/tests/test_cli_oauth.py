from __future__ import annotations

import json
from pathlib import Path

import pytest

from adaptorch_cli import cli, config_store


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ADAPTORCH_CONFIG_DIR", str(tmp_path))
    for name in (
        "ADAPTORCH_PROVIDER",
        "ADAPTORCH_PROVIDER_MODEL",
        "ADAPTORCH_PROVIDER_API_KEY",
        "ADAPTORCH_PROVIDER_AUTH_TYPE",
        "ADAPTORCH_PROVIDER_ACCOUNT_ID",
    ):
        monkeypatch.delenv(name, raising=False)


def test_cli_resolves_oauth_from_environment_without_persisting_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in {
        "ADAPTORCH_PROVIDER": "openai_codex",
        "ADAPTORCH_PROVIDER_MODEL": "gpt-5-codex",
        "ADAPTORCH_PROVIDER_API_KEY": "synthetic-oauth-token",
        "ADAPTORCH_PROVIDER_AUTH_TYPE": "oauth",
        "ADAPTORCH_PROVIDER_ACCOUNT_ID": "caller-account",
    }.items():
        monkeypatch.setenv(name, value)
    credential = cli._submission_credential()
    assert credential is not None
    assert credential.headers["X-Provider-Auth-Type"] == "oauth"
    assert credential.headers["X-Provider-Account-Id"] == "caller-account"
    assert not config_store.config_path().exists()


def test_cli_environment_credential_never_borrows_account_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_store.save_config(
        {
            "provider": {
                "provider": "openai_codex",
                "model": "gpt-5-codex",
                "api_key": "old-token",
                "auth_type": "oauth",
                "account_id": "old-account",
            }
        }
    )
    monkeypatch.setenv("ADAPTORCH_PROVIDER", "openai_codex")
    monkeypatch.setenv("ADAPTORCH_PROVIDER_MODEL", "gpt-5-codex")
    monkeypatch.setenv("ADAPTORCH_PROVIDER_API_KEY", "new-token")
    credential = cli._submission_credential()
    assert credential is not None
    assert credential.account_id is None
    assert credential.api_key == "new-token"


def test_cli_oauth_config_keys_and_view_are_safe() -> None:
    config_store.set_config_value("provider.name", "openai_codex")
    config_store.set_config_value("provider.model", "gpt-5-codex")
    config_store.set_config_value("provider.api_key", "synthetic-oauth-token")
    config_store.set_config_value("provider.auth_type", "oauth")
    config_store.set_config_value("provider.account_id", "caller-account")
    credential = cli._submission_credential()
    assert credential is not None and credential.account_id == "caller-account"
    view = json.dumps(config_store.config_view())
    assert "synthetic-oauth-token" not in view
    assert "caller-account" not in view
    assert config_store.config_view()["provider"]["account_id_configured"] is True
