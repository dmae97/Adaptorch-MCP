from __future__ import annotations

import json

import pytest
from client_test_support import LocalAPIServer, make_run_payload

import adaptorch_client
from adaptorch_client import AdaptOrchAPIError, AdaptOrchClient, ClientConfig


@pytest.mark.parametrize("field", ["provider", "model", "api_key"])
@pytest.mark.parametrize("value", ["", "x\r\nInjected: yes", "x\x00y", "non-header-한글"])
def test_provider_credentials_reject_invalid_header_values(field: str, value: str) -> None:
    values = {"provider": "openai", "model": "example-model", "api_key": "example-secret"}
    values[field] = value
    with pytest.raises(ValueError):
        adaptorch_client.ProviderCredential(**values)


def test_run_credential_is_secret_safe_and_used_only_on_the_submission(
    local_api: LocalAPIServer,
) -> None:
    credential = adaptorch_client.ProviderCredential("openai", "example-model", "provider-secret")
    assert credential.api_key not in repr(credential)
    client = AdaptOrchClient(ClientConfig(api_url=local_api.api_url, api_key="service-secret"))
    local_api.enqueue_json(make_run_payload())
    local_api.enqueue_json({"items": []})
    client.submit_run(
        {"subtasks": [{"id": "t1"}]},
        "11111111-1111-4111-8111-111111111111",
        provider_credential=credential,
    )
    client.list_runs()
    submitted, read = local_api.requests
    headers = {key.lower(): value for key, value in submitted.headers.items()}
    assert headers["x-provider"] == "openai"
    assert headers["x-provider-model"] == "example-model"
    assert headers["x-provider-key"] == "provider-secret"
    assert "provider-secret" not in submitted.body.decode()
    assert all(not key.lower().startswith("x-provider") for key in read.headers)


def test_fastapi_detail_is_useful_but_neither_credential_is_echoed(
    local_api: LocalAPIServer,
) -> None:
    credential = adaptorch_client.ProviderCredential("openai", "example-model", "provider-secret")
    client = AdaptOrchClient(ClientConfig(api_url=local_api.api_url, api_key="service-secret"))
    local_api.enqueue_json(
        {"detail": "request_provider_rejected: provider-secret service-secret"}, status=503
    )
    with pytest.raises(AdaptOrchAPIError) as caught:
        client.submit_run(
            {}, "11111111-1111-4111-8111-111111111111", provider_credential=credential
        )
    assert caught.value.status_code == 503
    assert caught.value.code == "request_provider_rejected"
    assert "provider-secret" not in str(caught.value)
    assert "service-secret" not in str(caught.value)


def test_artifact_map_names_are_available_without_fabricating_download_urls(
    local_api: LocalAPIServer,
) -> None:
    payload = {"run_id": "run-1", "artifacts": {"result_json": "/private/path/result.json"}}
    local_api.enqueue_json(payload)
    result = AdaptOrchClient(
        ClientConfig(api_url=local_api.api_url, api_key="test")
    ).list_artifacts("run-1")
    assert result.items[0].artifact_id == "result_json"
    assert result.items[0].name == "result_json"
    assert result.items[0].download_url is None
    assert result.items[0].size_bytes is None
    assert json.dumps(result.to_payload()) == json.dumps(payload)
