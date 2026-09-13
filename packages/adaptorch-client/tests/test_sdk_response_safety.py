"""Public SDK parsing errors must not leak reflected credentials or raw recursion errors."""

from __future__ import annotations

import pytest
from client_test_support import LocalAPIServer

from adaptorch_client import (
    AdaptOrchAPIError,
    AdaptOrchClient,
    ClientConfig,
    JSONMapping,
    JSONValue,
    ProviderCredential,
)


def _nested(depth: int) -> JSONValue:
    value: JSONValue = None
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.parametrize("reflected", ["ado_sdk-test-key", "provider-sdk-test-key"])
def test_response_validation_never_echoes_an_untrusted_link_key(
    local_api: LocalAPIServer,
    reflected: str,
) -> None:
    client = AdaptOrchClient(ClientConfig(local_api.api_url, "ado_sdk-test-key"))
    credential = ProviderCredential("p", "m", "provider-sdk-test-key")
    local_api.enqueue_json(
        {"run_id": "r1", "status": "QUEUED", "links": {reflected: 1}}, status=201
    )
    with pytest.raises(AdaptOrchAPIError) as error:
        client.submit_run(
            {}, "11111111-1111-4111-8111-111111111111", provider_credential=credential
        )
    assert reflected not in str(error.value) and reflected not in repr(error.value)
    assert len(local_api.requests) == 1


def test_deep_response_fails_with_public_error_not_raw_recursion(local_api: LocalAPIServer) -> None:
    client = AdaptOrchClient(ClientConfig(local_api.api_url, "ado_sdk-test-key"))
    local_api.enqueue_json({"run_id": "r1", "status": "SUCCEEDED", "extension": _nested(500)})
    with pytest.raises(AdaptOrchAPIError):
        client.get_run("r1")
    assert len(local_api.requests) == 1


def test_deep_request_is_rejected_before_network(local_api: LocalAPIServer) -> None:
    client = AdaptOrchClient(ClientConfig(local_api.api_url, "ado_sdk-test-key"))
    payload: JSONMapping = {"extension": _nested(2000)}
    with pytest.raises(AdaptOrchAPIError):
        client.submit_run(payload, "11111111-1111-4111-8111-111111111111")
    assert local_api.requests == []
