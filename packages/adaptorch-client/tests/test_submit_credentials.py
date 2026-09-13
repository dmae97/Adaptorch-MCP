from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPResponse
from typing import Literal
from urllib.error import HTTPError
from urllib.request import OpenerDirector, Request

import pytest
from client_test_support import JSONMapping, LocalAPIServer

from adaptorch_client import AdaptOrchAPIError, ClientConfig
from adaptorch_client.provider import ProviderCredential
from adaptorch_client.transport import HTTPTransport, RequestSpec


def _transport(local_api: LocalAPIServer, key: str = "ado_synthetic-service") -> HTTPTransport:
    return HTTPTransport(ClientConfig(local_api.api_url, key, timeout_seconds=1.0))


@pytest.mark.parametrize("method,path", [("GET", "/v1/whoami"), ("POST", "/v1/runs")])
def test_generic_headers_cannot_forge_provider_or_auth_headers(
    local_api: LocalAPIServer, method: Literal["GET", "POST"], path: str
) -> None:
    local_api.enqueue_json({"ok": True})
    headers = {
        "x-pRoViDeR-kEy": "synthetic-forged",
        "x-PrOvIdEr": "forged",
        "X-Provider-Name": "forged",
        "X-Provider-Model": "forged",
        "X-Provider-Extra": "forged",
        "AUTHORIZATION": "Bearer forged",
        "x-api-key": "forged",
        "Idempotency-Key": "11111111-1111-4111-8111-111111111111",
    }

    _transport(local_api).request(RequestSpec(method, path, headers=headers))

    sent = {name.lower(): value for name, value in local_api.requests[0].headers.items()}
    assert not any(name.startswith("x-provider") for name in sent)
    assert sent["x-api-key"] == "ado_synthetic-service"
    assert "authorization" not in sent
    assert sent["idempotency-key"] == headers["Idempotency-Key"]
    assert headers["x-pRoViDeR-kEy"] == "synthetic-forged"


@pytest.mark.parametrize("status", [200, 400])
@pytest.mark.parametrize(
    "body",
    [
        b'{"ok":1,"ok":2}',
        b'{"items":[{"key":1,"key":2}]}',
        b'{"error":{"code":"unsafe","message":"private","message":"hidden"}}',
        b'{"key":1,"\\u006bey":2}',
    ],
)
def test_duplicate_json_keys_fail_closed_at_every_depth(
    local_api: LocalAPIServer, status: int, body: bytes
) -> None:
    local_api.enqueue_raw(body, status=status)

    with pytest.raises(AdaptOrchAPIError) as raised:
        _transport(local_api).request(RequestSpec("GET", "/v1/whoami"))

    assert raised.value.code is None
    assert "private" not in str(raised.value)
    assert "hidden" not in str(raised.value)
    assert raised.value.status_code == (status if status >= 400 else None)


@pytest.mark.parametrize("status", [200, 400])
@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_finite_json_guard_survives_strict_object_parsing(
    local_api: LocalAPIServer, status: int, token: str
) -> None:
    local_api.enqueue_raw(
        f'{{"error":{{"code":"unsafe","number":{token}}}}}'.encode(), status=status
    )

    with pytest.raises(AdaptOrchAPIError) as raised:
        _transport(local_api).request(RequestSpec("GET", "/v1/whoami"))

    assert raised.value.code is None
    assert raised.value.status_code == (status if status >= 400 else None)


@pytest.mark.parametrize(
    "body,headers",
    [
        (b'{"error":{"message":"denied"}}', {}),
        (b'{"bad":', {}),
        (b"{}", {"Content-Length": "9000000"}),
        (b"{}", {"Content-Length": "-1"}),
        (b"{}", {"Content-Length": "invalid"}),
        (b"{}", {"Content-Length": "200"}),
        (b"invalid\r\n", {"Transfer-Encoding": "chunked"}),
    ],
)
def test_http_error_responses_are_closed_on_all_decode_paths(
    local_api: LocalAPIServer,
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    headers: dict[str, str],
) -> None:
    local_api.enqueue_raw(body, status=400, headers=headers)
    original_open = OpenerDirector.open
    observed: list[HTTPError] = []

    def capture_error(self: OpenerDirector, request: Request, *, timeout: float) -> None:
        with pytest.raises(HTTPError) as caught:
            original_open(self, request, timeout=timeout)
        observed.append(caught.value)
        raise caught.value

    monkeypatch.setattr(OpenerDirector, "open", capture_error)

    with pytest.raises(AdaptOrchAPIError) as raised:
        _transport(local_api).request(RequestSpec("GET", "/v1/whoami"))

    assert len(observed) == 1
    assert observed[0].closed
    assert raised.value.status_code == 400


@pytest.mark.parametrize("override,expected", [(None, 1.0), (0.25, 0.25), (1.0, 1.0), (5.0, 1.0)])
def test_timeout_override_only_shortens_configured_timeout(
    local_api: LocalAPIServer,
    monkeypatch: pytest.MonkeyPatch,
    override: float | None,
    expected: float,
) -> None:
    original_open = OpenerDirector.open
    observed: list[float] = []

    def record_timeout(self: OpenerDirector, request: Request, *, timeout: float) -> HTTPResponse:
        observed.append(timeout)
        response = original_open(self, request, timeout=timeout)
        assert isinstance(response, HTTPResponse)
        return response

    monkeypatch.setattr(OpenerDirector, "open", record_timeout)
    for _ in range(2):
        local_api.enqueue_json({"ok": True})
    transport = _transport(local_api)

    transport.request(RequestSpec("GET", "/v1/whoami", timeout_seconds=override))
    transport.request(RequestSpec("GET", "/v1/whoami"))

    assert observed == [expected, 1.0]


def test_transport_does_not_discover_environment_proxies(
    local_api: LocalAPIServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_api.enqueue_json({"ok": True})

    def forbid_discovery() -> None:
        pytest.fail("transport must not discover environment proxies")

    monkeypatch.setattr("urllib.request.getproxies", forbid_discovery)

    assert _transport(local_api).request(RequestSpec("GET", "/v1/whoami")) == {"ok": True}


@pytest.mark.parametrize("key", ["ado_synthetic-service", "synthetic-bearer"])
def test_submit_credential_is_headers_only_and_does_not_persist(
    local_api: LocalAPIServer,
    key: str,
) -> None:
    credential = ProviderCredential("test-provider", "test/model", "synthetic-byok")
    transport = _transport(local_api, key)
    for _ in range(3):
        local_api.enqueue_json({"ok": True})
    headers = {
        "x-PrOvIdEr": "forged",
        "X-Provider-Name": "forged",
        "X-Provider-Key": "forged",
        "X-Provider-Extra": "forged",
        "Authorization": "forged",
        "X-API-Key": "forged",
    }

    transport.request(RequestSpec("POST", "/v1/runs", {"goal": "test"}, headers, credential))
    transport.request(RequestSpec("GET", "/v1/runs/run-1"))
    transport.request(RequestSpec("POST", "/v1/runs", {"goal": "next"}))

    sent = {name.lower(): value for name, value in local_api.requests[0].headers.items()}
    assert {name: value for name, value in sent.items() if name.startswith("x-provider")} == {
        "x-provider": "test-provider",
        "x-provider-model": "test/model",
        "x-provider-key": "synthetic-byok",
    }
    auth = {name: value for name, value in sent.items() if name in {"x-api-key", "authorization"}}
    assert auth == (
        {"x-api-key": key} if key.startswith("ado_") else {"authorization": f"Bearer {key}"}
    )
    assert json.loads(local_api.requests[0].body) == {"goal": "test"}
    assert all(
        not any(name.lower().startswith("x-provider") for name in request.headers)
        for request in local_api.requests[1:]
    )
    assert headers["X-Provider-Key"] == "forged"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308, 429, 503])
def test_byok_post_never_redirects_or_retries(local_api: LocalAPIServer, status: int) -> None:
    credential = ProviderCredential("test", "model", "synthetic-byok")
    local_api.enqueue_raw(
        b"{}",
        status=status,
        headers={
            "Location": f"{local_api.api_url}/credential-sink",
            "Retry-After": "0",
        },
    )

    with pytest.raises(AdaptOrchAPIError) as raised:
        _transport(local_api).request(
            RequestSpec("POST", "/v1/runs", provider_credential=credential)
        )

    assert raised.value.status_code == status
    assert [(request.method, request.path) for request in local_api.requests] == [
        ("POST", "/v1/runs")
    ]


@pytest.mark.parametrize(
    "service,provider",
    [
        ("synthetic-service", "synthetic-byok"),
        ("synthetic-key", "synthetic-key-with-private-suffix"),
        ("synthetic-key-with-private-suffix", "synthetic-key"),
        ("synthetic service", "synthetic provider"),
    ],
)
def test_api_errors_redact_both_credentials_before_truncation(
    local_api: LocalAPIServer,
    service: str,
    provider: str,
) -> None:
    credential = ProviderCredential("test", "model", provider)
    wire_service = service.replace(" ", "\n")
    wire_provider = provider.replace(" ", "\n")
    local_api.enqueue_json(
        {
            "error": {
                "code": f"{wire_service}\n{wire_provider}",
                "message": f"{wire_provider}\t{wire_service}" + "!" * 600,
                "details": {"private": "private-details"},
            }
        },
        status=401,
    )

    with pytest.raises(AdaptOrchAPIError) as raised:
        _transport(local_api, service).request(
            RequestSpec("POST", "/v1/runs", provider_credential=credential)
        )

    error = raised.value
    for value in (str(error), repr(error), repr(error.args), error.code or ""):
        assert service not in value and provider not in value
        assert "private-suffix" not in value and "private-details" not in value
    assert error.code == "[redacted] [redacted]"
    assert len(str(error).rsplit(": ", 1)[-1]) == 500
    assert error.status_code == 401


def test_concurrent_credentials_and_redaction_are_request_local(local_api: LocalAPIServer) -> None:
    keys = ("synthetic-byok-a", "synthetic-byok-b")
    transport = _transport(local_api)
    for _ in keys:
        local_api.enqueue_json(
            {"error": {"code": "DENIED", "message": " | ".join(keys)}}, status=403
        )

    def submit(key: str) -> str:
        credential = ProviderCredential("test", "model", key)
        with pytest.raises(AdaptOrchAPIError) as raised:
            transport.request(RequestSpec("POST", "/v1/runs", provider_credential=credential))
        return str(raised.value)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, keys))

    assert keys[0] not in results[0] and keys[1] in results[0]
    assert keys[1] not in results[1] and keys[0] in results[1]
    sent = [
        {name.lower(): value for name, value in request.headers.items()}
        for request in local_api.requests
    ]
    assert {headers["x-provider-key"] for headers in sent} == set(keys)


def test_duplicate_guard_allows_keys_reused_in_distinct_objects(local_api: LocalAPIServer) -> None:
    payload: JSONMapping = {"items": [{"key": 1}, {"key": 2}]}
    local_api.enqueue_json(payload)

    assert _transport(local_api).request(RequestSpec("GET", "/v1/whoami")) == payload
