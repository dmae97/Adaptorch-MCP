from __future__ import annotations

import pytest

import adaptorch_client
from adaptorch_client import (
    AdaptOrchAPIError,
    AdaptOrchClient,
    ArtifactListResponse,
    CapabilitySet,
    ClientConfig,
    EvidenceReport,
    PayloadResult,
    Principal,
    Run,
    RunListResponse,
    validate_api_url,
)


def test_package_exports_public_client_contract() -> None:
    assert adaptorch_client.AdaptOrchClient is AdaptOrchClient
    assert adaptorch_client.ClientConfig is ClientConfig
    assert adaptorch_client.AdaptOrchAPIError is AdaptOrchAPIError
    assert adaptorch_client.validate_api_url is validate_api_url


def test_package_exports_typed_response_contract() -> None:
    for name in (
        "Artifact",
        "ArtifactListResponse",
        "CapabilitySet",
        "EvidenceCheck",
        "EvidenceReport",
        "JSONMapping",
        "JSONValue",
        "PayloadResult",
        "Principal",
        "Run",
        "RunListResponse",
        "validate_api_url",
    ):
        assert name in adaptorch_client.__all__
        assert hasattr(adaptorch_client, name)


def test_response_types_preserve_payload_result_contract() -> None:
    response_types: tuple[type[PayloadResult], ...] = (
        ArtifactListResponse,
        CapabilitySet,
        EvidenceReport,
        Principal,
        Run,
        RunListResponse,
    )
    for response_type in response_types:
        assert issubclass(response_type, PayloadResult)


def test_client_config_accepts_required_fields() -> None:
    config = ClientConfig(
        api_url="https://api.example.com",
        api_key="test-api-key",
        timeout_seconds=12.5,
    )

    assert config.api_url == "https://api.example.com"
    assert config.api_key == "test-api-key"
    assert config.timeout_seconds == 12.5


def test_client_config_rejects_non_header_api_key() -> None:
    with pytest.raises(ValueError):
        ClientConfig(
            api_url="https://api.example.com",
            api_key="invalid-\u20ac-key",
        )


@pytest.mark.parametrize(
    "api_url",
    [
        "https://api.example.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
    ],
)
def test_client_config_allows_https_and_loopback_http(api_url: str) -> None:
    config = ClientConfig(api_url=api_url, api_key="test-api-key", timeout_seconds=1.0)

    assert config.api_url == api_url


@pytest.mark.parametrize(
    "api_url",
    [
        "http://api.example.com",
        "http://localhost.evil.example",
        "ftp://api.example.com",
        "https://user:password@api.example.com",
        "http://user:password@localhost:8000",
    ],
)
def test_client_config_rejects_insecure_or_credentialed_urls(api_url: str) -> None:
    with pytest.raises(ValueError):
        ClientConfig(api_url=api_url, api_key="test-api-key", timeout_seconds=1.0)


def test_validate_api_url_normalizes_and_is_reused_by_config() -> None:
    assert validate_api_url("https://api.example.com/") == "https://api.example.com"
    assert validate_api_url("https://api.example.com") == "https://api.example.com"

    config = ClientConfig(
        api_url="https://api.example.com/",
        api_key="test-api-key",
        timeout_seconds=1.0,
    )
    assert config.api_url == "https://api.example.com"


@pytest.mark.parametrize(
    "api_url",
    [
        "http://api.example.com",
        "https://user:password@api.example.com",
        "https://api.example.com/path",
        "https://api.example.com?x=1",
        "https://api.example.com#fragment",
        "https://api.example.com:0",
        " https://api.example.com",
        "https://api.example.com\\evil",
        "https://api.example.com\x00",
        "https://api.example.com\x7f",
        "ftp://api.example.com",
        "https://",
    ],
)
def test_validate_api_url_rejects_unsafe_urls(api_url: str) -> None:
    with pytest.raises(ValueError):
        validate_api_url(api_url)
