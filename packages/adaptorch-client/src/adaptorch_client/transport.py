"""Bounded, redirect-free standard-library HTTP transport."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import Message
from http.client import HTTPException
from typing import IO, Literal, Never, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from adaptorch_client.config import ClientConfig
from adaptorch_client.errors import AdaptOrchAPIError
from adaptorch_client.json_limits import require_json_depth
from adaptorch_client.models import JSONMapping, JSONValue
from adaptorch_client.provider import ProviderCredential, sanitize_error

_MAX_REQUEST_BYTES = 8 * 1024 * 1024
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_ERROR_CODE_LENGTH = 100
_MAX_ERROR_MESSAGE_LENGTH = 500


def _reject_json_constant(_value: str) -> Never:
    raise ValueError("non-finite JSON number")


def _parse_finite_float(text: str) -> float:
    """Reject JSON numbers that are unparseable or not finite.

    Raising ValueError is this hook's contract; _decode_mapping catches it and
    reports AdaptOrchAPIError. As the parse_float hook the input is always a
    valid number token, where overflow like 1e999 yields inf rather than an
    exception, so the finiteness check carries the rejection. The parse guard
    keeps the same single failure type if the helper is ever called directly.
    """
    try:
        value = float(text)
    except ValueError:
        raise ValueError("unparseable JSON number") from None
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def _unique_object(pairs: list[tuple[str, JSONValue]]) -> JSONMapping:
    result: JSONMapping = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


class _ReadableResponse(Protocol):
    # Both a success response and an HTTPError are read through this protocol.
    # headers must be a read-only property: declaring it as a mutable attribute
    # makes it invariant, which rejects HTTPError's property. read takes its
    # size positionally because the standard library names that parameter n.
    @property
    def headers(self) -> Message: ...

    def read(self, amount: int = -1, /) -> bytes: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> Request | None:
        """Reject every redirect instead of forwarding credentials."""
        return None


@dataclass(frozen=True, slots=True)
class RequestSpec:
    method: Literal["GET", "POST", "PUT"]
    path: str
    payload: Mapping[str, JSONValue] | None = None
    headers: Mapping[str, str] | None = field(default=None, repr=False)
    provider_credential: ProviderCredential | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.provider_credential is not None and (self.method, self.path) != (
            "POST",
            "/v1/runs",
        ):
            raise ValueError("provider_credential is allowed only for POST /v1/runs")
        if self.timeout_seconds is not None:
            if type(self.timeout_seconds) not in (int, float):
                raise ValueError("timeout_seconds must be positive and finite")
            try:
                valid_timeout = self.timeout_seconds > 0 and math.isfinite(self.timeout_seconds)
            except OverflowError:
                valid_timeout = False
            if not valid_timeout:
                raise ValueError("timeout_seconds must be positive and finite")


class HTTPTransport:
    """Execute one authenticated HTTP request without retries."""

    __slots__ = ("_config",)

    def __init__(self, config: ClientConfig) -> None:
        self._config = config

    def request(self, spec: RequestSpec) -> JSONMapping:
        """Execute one request and return the decoded JSON object."""
        body = self._encode_payload(spec.payload)
        headers = {
            "Accept": "application/json",
            **{
                name: value
                for name, value in (spec.headers or {}).items()
                if name.lower() not in {"authorization", "x-api-key", "x-provider"}
                and not name.lower().startswith("x-provider-")
            },
            **self._config.auth_headers,
        }
        if spec.provider_credential is not None:
            headers.update(spec.provider_credential.headers)
        if body is not None:
            headers["Content-Type"] = "application/json"

        request = Request(
            f"{self._config.api_url}{spec.path}",
            data=body,
            headers=headers,
            method=spec.method,
        )
        timeout = self._config.timeout_seconds
        if spec.timeout_seconds is not None:
            timeout = min(timeout, spec.timeout_seconds)
        try:
            with build_opener(ProxyHandler({}), _NoRedirectHandler()).open(
                request,
                timeout=timeout,
            ) as response:
                return self._decode_mapping(self._read_bounded(response))
        except HTTPError as error:
            with error:
                raise self._from_http_error(error, spec.provider_credential) from None
        except (HTTPException, URLError, TimeoutError, OSError):
            raise AdaptOrchAPIError("AdaptOrch network request failed") from None

    @staticmethod
    def _encode_payload(payload: Mapping[str, JSONValue] | None) -> bytes | None:
        if payload is None:
            return None
        try:
            text = json.dumps(
                dict(payload),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            require_json_depth(text)
            encoded = text.encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise AdaptOrchAPIError("AdaptOrch request JSON could not be encoded") from None
        if len(encoded) > _MAX_REQUEST_BYTES:
            raise AdaptOrchAPIError("AdaptOrch request JSON exceeds the size limit")
        return encoded

    @staticmethod
    def _read_bounded(response: _ReadableResponse) -> bytes:
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                raise AdaptOrchAPIError("AdaptOrch response has an invalid size") from None
            if declared_length < 0 or declared_length > _MAX_RESPONSE_BYTES:
                raise AdaptOrchAPIError("AdaptOrch response exceeds the size limit")

        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise AdaptOrchAPIError("AdaptOrch response exceeds the size limit")
        return body

    @staticmethod
    def _decode_mapping(body: bytes) -> JSONMapping:
        try:
            text = body.decode("utf-8-sig")
            require_json_depth(text)
            decoded: JSONValue = json.loads(
                text,
                parse_constant=_reject_json_constant,
                parse_float=_parse_finite_float,
                object_pairs_hook=_unique_object,
            )
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise AdaptOrchAPIError("AdaptOrch returned invalid JSON") from None
        if not isinstance(decoded, dict):
            raise AdaptOrchAPIError("AdaptOrch returned a non-object JSON response")
        return decoded

    def _from_http_error(
        self,
        error: HTTPError,
        credential: ProviderCredential | None,
    ) -> AdaptOrchAPIError:
        try:
            body = self._read_bounded(error)
            decoded = self._decode_mapping(body)
        except (AdaptOrchAPIError, HTTPException, OSError):
            return AdaptOrchAPIError(
                f"AdaptOrch API request failed with HTTP {error.code}",
                status_code=error.code,
            )

        secrets: tuple[str, ...] = (self._config.api_key,)
        if credential is not None:
            secrets += (credential.api_key,)
            if credential.account_id is not None:
                secrets += (credential.account_id,)
        error_value = decoded.get("error", decoded.get("detail"))
        if isinstance(error_value, str):
            message = sanitize_error(error_value, secrets, _MAX_ERROR_MESSAGE_LENGTH)
            prefix, separator, _ = message.partition(":")
            code = prefix if separator and re.fullmatch(r"[a-z][a-z0-9_]{0,99}", prefix) else None
            return AdaptOrchAPIError(
                f"AdaptOrch API request failed with HTTP {error.code}: {message}",
                status_code=error.code,
                code=code,
            )
        if not isinstance(error_value, dict):
            return AdaptOrchAPIError(
                f"AdaptOrch API request failed with HTTP {error.code}",
                status_code=error.code,
            )

        code_value = error_value.get("code")
        message_value = error_value.get("message")
        code = (
            sanitize_error(code_value, secrets, _MAX_ERROR_CODE_LENGTH)
            if isinstance(code_value, str)
            else None
        )
        message = (
            sanitize_error(message_value, secrets, _MAX_ERROR_MESSAGE_LENGTH)
            if isinstance(message_value, str)
            else "request failed"
        )
        prefix = f"AdaptOrch API error {code}" if code else "AdaptOrch API error"
        return AdaptOrchAPIError(
            f"{prefix}: {message}",
            status_code=error.code,
            code=code,
        )
