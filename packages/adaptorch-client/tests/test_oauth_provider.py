from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest
from client_test_support import LocalAPIServer

from adaptorch_client import ClientConfig
from adaptorch_client.errors import AdaptOrchAPIError
from adaptorch_client.provider import ProviderCredential
from adaptorch_client.transport import HTTPTransport, RequestSpec


def test_oauth_headers_are_submit_only_and_secret_safe(local_api: LocalAPIServer) -> None:
    # Given: an explicit caller-owned OAuth credential, not a process env lookup.
    credential = ProviderCredential(
        "openai_codex",
        "gpt-5-codex",
        "synthetic-oauth-token",
        auth_type="oauth",
        account_id="caller-account",
    )
    transport = HTTPTransport(ClientConfig(local_api.api_url, "synthetic-tenant-key"))
    local_api.enqueue_json({"run_id": "run-one"}, status=201)
    local_api.enqueue_json({"status": "SUCCEEDED"})
    # When: submission is followed by polling.
    transport.request(RequestSpec("POST", "/v1/runs", provider_credential=credential))
    transport.request(RequestSpec("GET", "/v1/runs/run-one"))
    # Then: only the submission carries OAuth metadata, never its body or repr.
    first = {k.lower(): v for k, v in local_api.requests[0].headers.items()}
    second = {k.lower(): v for k, v in local_api.requests[1].headers.items()}
    assert first["x-provider-auth-type"] == "oauth"
    assert first["x-provider-account-id"] == "caller-account"
    assert first["x-provider-key"] == "synthetic-oauth-token"
    assert not any(k.startswith("x-provider") for k in second)
    assert "synthetic-oauth-token" not in repr(credential)
    assert "caller-account" not in repr(credential)


@pytest.mark.parametrize(
    "field,value",
    [
        ("auth_type", "cookie"),
        ("auth_type", False),
        ("auth_type", []),
        ("account_id", "bad\r\nheader"),
        ("account_id", 7),
        ("api_key", '{"refresh_token":"do-not-send"}'),
    ],
)
def test_oauth_rejects_malformed_metadata(field: str, value: object) -> None:
    kwargs: dict[str, object] = dict(
        provider="openai_codex", model="gpt-5-codex", api_key="test-token", auth_type="oauth"
    )
    kwargs[field] = value
    construct = cast(Callable[..., ProviderCredential], ProviderCredential)
    with pytest.raises(ValueError):
        construct(**kwargs)


def test_oauth_reflected_token_and_account_are_redacted(local_api: LocalAPIServer) -> None:
    # Given: a server error reflects submitted authentication values.
    credential = ProviderCredential(
        "openai_codex", "gpt-5-codex", "synthetic-oauth-token", account_id="caller-account"
    )
    local_api.enqueue_json({"detail": "rejected synthetic-oauth-token caller-account"}, status=401)
    transport = HTTPTransport(ClientConfig(local_api.api_url, "tenant-key"))
    # When/Then: neither value escapes the transport boundary in an exception.
    with pytest.raises(AdaptOrchAPIError) as error:
        transport.request(RequestSpec("POST", "/v1/runs", provider_credential=credential))
    assert "synthetic-oauth-token" not in str(error.value)
    assert "caller-account" not in str(error.value)
