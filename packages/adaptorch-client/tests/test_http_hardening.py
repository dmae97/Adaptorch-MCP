from __future__ import annotations

import pytest
from client_test_support import JSONMapping, LocalAPIServer, make_run_payload

from adaptorch_client import AdaptOrchAPIError, AdaptOrchClient, ClientConfig


def _client(local_api: LocalAPIServer, *, api_key: str = "test-api-key") -> AdaptOrchClient:
    return AdaptOrchClient(
        ClientConfig(api_url=local_api.api_url, api_key=api_key, timeout_seconds=1.0)
    )


def test_submit_run_does_not_retry_transient_post_failure(
    local_api: LocalAPIServer,
) -> None:
    error_payload: JSONMapping = {
        "error": {"code": "SERVICE_UNAVAILABLE", "message": "try later"}
    }
    local_api.enqueue_json(error_payload, status=503)

    with pytest.raises(AdaptOrchAPIError):
        _client(local_api).submit_run({"goal": "one attempt"}, "idem-one-attempt")

    assert len(local_api.requests) == 1
    assert local_api.requests[0].method == "POST"
    assert local_api.requests[0].path == "/v1/runs"


def test_api_error_message_excludes_credentials_and_private_details(
    local_api: LocalAPIServer,
) -> None:
    api_key = "test-api-key-do-not-leak"
    error_payload: JSONMapping = {
        "error": {
            "code": "INVALID_API_KEY",
            "message": "authentication failed",
            "details": {
                "authorization": f"Bearer {api_key}",
                "debug": "private-server-stack",
            },
        }
    }
    local_api.enqueue_json(error_payload, status=401)

    with pytest.raises(AdaptOrchAPIError) as raised:
        _client(local_api, api_key=api_key).whoami()

    message = str(raised.value)
    assert "INVALID_API_KEY" in message
    assert "authentication failed" in message
    assert api_key not in message
    assert "private-server-stack" not in message
    assert "Authorization" not in message


def test_client_rejects_oversized_response_before_parsing(
    local_api: LocalAPIServer,
) -> None:
    oversized_json = b'{"padding":"' + (b"x" * (8 * 1024 * 1024)) + b'"}'
    local_api.enqueue_raw(
        oversized_json,
        headers={"Content-Type": "application/json"},
    )

    with pytest.raises(AdaptOrchAPIError, match="(?i)(large|size|limit)"):
        _client(local_api).capabilities()


def test_client_maps_malformed_json_to_sanitized_api_error(
    local_api: LocalAPIServer,
) -> None:
    local_api.enqueue_raw(
        b'{"private":"raw-response-must-not-leak"',
        headers={"Content-Type": "application/json"},
    )

    with pytest.raises(AdaptOrchAPIError) as raised:
        _client(local_api).capabilities()

    assert "raw-response-must-not-leak" not in str(raised.value)


def test_client_rejects_non_mapping_json_response(local_api: LocalAPIServer) -> None:
    local_api.enqueue_raw(b"[]", headers={"Content-Type": "application/json"})

    with pytest.raises(AdaptOrchAPIError):
        _client(local_api).capabilities()


def test_client_rejects_redirect_without_forwarding_credentials(
    local_api: LocalAPIServer,
) -> None:
    local_api.enqueue_raw(
        b"",
        status=302,
        headers={"Location": f"{local_api.api_url}/redirect-target"},
    )

    with pytest.raises(AdaptOrchAPIError) as raised:
        _client(local_api).capabilities()

    assert raised.value.status_code == 302
    assert len(local_api.requests) == 1
    assert local_api.requests[0].path == "/v1/capabilities"


@pytest.mark.parametrize(
    "body",
    [
        b'{"data": 1e999}',
        b'{"data": -1e999}',
        b'{"data": NaN}',
        b'{"data": Infinity}',
        b'{"data": -Infinity}',
    ],
)
def test_client_rejects_non_finite_json_numbers(local_api: LocalAPIServer, body: bytes) -> None:
    local_api.enqueue_raw(body, headers={"Content-Type": "application/json"})

    with pytest.raises(AdaptOrchAPIError):
        _client(local_api).capabilities()


def test_submit_run_rejects_oversized_request_before_network(
    local_api: LocalAPIServer,
) -> None:
    oversized_spec: JSONMapping = {"goal": "x" * (8 * 1024 * 1024)}

    with pytest.raises(AdaptOrchAPIError, match="(?i)(large|size|limit)"):
        _client(local_api).submit_run(oversized_spec, "idem-oversized")

    assert local_api.requests == []


@pytest.mark.parametrize(
    "idempotency_key",
    [
        "",
        "k" * 201,
        "bad\rkey",
        "bad\nkey",
        "bad\x00key",
        "bad\tkey",
        "bad\x1fkey",
        "bad\x7fkey",
        "bad\u20ackey",
    ],
)
def test_submit_run_rejects_invalid_idempotency_key(
    local_api: LocalAPIServer, idempotency_key: str
) -> None:
    with pytest.raises(ValueError):
        _client(local_api).submit_run({"goal": "guarded"}, idempotency_key)

    assert local_api.requests == []


@pytest.mark.parametrize("idempotency_key", ["k", "k" * 200])
def test_submit_run_accepts_boundary_idempotency_keys(
    local_api: LocalAPIServer, idempotency_key: str
) -> None:
    local_api.enqueue_json(make_run_payload(), status=202)

    _client(local_api).submit_run({"goal": "boundary"}, idempotency_key)

    assert local_api.requests[0].headers["Idempotency-Key"] == idempotency_key
