from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields, replace
from typing import Literal

import pytest
from client_test_support import JSONValue, LocalAPIServer

from adaptorch_client import ClientConfig
from adaptorch_client.provider import ProviderCredential
from adaptorch_client.transport import HTTPTransport, RequestSpec


@pytest.mark.parametrize("field_name", ["provider", "model", "api_key"])
def test_provider_credential_is_frozen_slotted_and_hides_key(field_name: str) -> None:
    credential = ProviderCredential("test-provider", "test/model", "synthetic-byok")

    with pytest.raises(FrozenInstanceError):
        setattr(credential, field_name, "synthetic-replacement")

    assert credential.api_key == "synthetic-byok"
    assert credential.provider == "test-provider" and credential.model == "test/model"
    assert "synthetic-byok" not in repr(credential)
    assert "synthetic-byok" not in repr(
        RequestSpec("POST", "/v1/runs", provider_credential=credential)
    )
    assert not hasattr(credential, "__dict__")
    assert not next(field for field in fields(credential) if field.name == "api_key").repr
    assert type(credential).__module__ == "adaptorch_client.provider"
    assert hash(credential) == hash(replace(credential))


@pytest.mark.parametrize("field_name", ["provider", "model", "api_key"])
@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        " leading",
        "trailing ",
        "bad\rheader",
        "bad\nheader",
        "bad\theader",
        "bad\x00header",
        "bad\x1fheader",
        "bad\x7fheader",
        "bad\x80header",
        "bad\x9fheader",
        "bad\xadheader",
        "bad\u20acheader",
        "bad\ud800header",
        pytest.param("x" * 4097, id="oversized"),
        None,
        True,
        123,
        [],
    ],
)
def test_credential_rejects_unsafe_header_values_without_echoing_them(
    field_name: str,
    value: JSONValue,
) -> None:
    values: dict[str, JSONValue] = {
        "provider": "test",
        "model": "model",
        "api_key": "synthetic-byok",
    }
    values[field_name] = value
    # Runtime callers can supply untyped data despite the public str annotations.
    construct: Callable[..., ProviderCredential] = ProviderCredential

    with pytest.raises(ValueError) as raised:
        construct(**values)

    assert field_name in str(raised.value)
    assert "synthetic-byok" not in str(raised.value)
    if isinstance(value, str) and value.strip():
        assert value not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "value",
    ["test-provider", "test/model:v1", "caf\xe9", pytest.param("x" * 4096, id="maximum-size")],
)
def test_credential_preserves_safe_header_values(value: str) -> None:
    credential = ProviderCredential(value, value, value)

    assert (credential.provider, credential.model, credential.api_key) == (value, value, value)


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/v1/runs"),
        ("PUT", "/v1/runs"),
        ("POST", "/v1/runs/"),
        ("POST", "/v1/runs?extra=1"),
        ("POST", "/v1/runs#fragment"),
        ("POST", "/v1/runs/run-1/cancel"),
        ("POST", "/v1/whoami"),
        ("POST", "/v1/runs/../whoami"),
        ("POST", "//other.invalid/v1/runs"),
        ("POST", "https://other.invalid/v1/runs"),
        ("POST", "/v1/%72uns"),
    ],
)
def test_provider_credential_is_rejected_outside_exact_submit_route_before_io(
    local_api: LocalAPIServer,
    method: Literal["GET", "POST", "PUT"],
    path: str,
) -> None:
    transport = HTTPTransport(ClientConfig(local_api.api_url, "synthetic-service"))
    credential = ProviderCredential("test", "model", "synthetic-byok")

    with pytest.raises(ValueError, match="provider_credential"):
        transport.request(RequestSpec(method, path, provider_credential=credential))

    assert local_api.requests == []


@pytest.mark.parametrize(
    "timeout",
    [
        True,
        False,
        0,
        -1,
        float("nan"),
        float("inf"),
        float("-inf"),
        "1.0",
        [],
        pytest.param(10**400, id="overflow"),
    ],
)
def test_timeout_override_rejects_invalid_values_before_io(
    local_api: LocalAPIServer,
    timeout: JSONValue,
) -> None:
    transport = HTTPTransport(ClientConfig(local_api.api_url, "synthetic-service"))
    construct: Callable[..., RequestSpec] = RequestSpec

    with pytest.raises(ValueError, match="timeout_seconds"):
        transport.request(construct("GET", "/v1/whoami", timeout_seconds=timeout))

    assert local_api.requests == []
