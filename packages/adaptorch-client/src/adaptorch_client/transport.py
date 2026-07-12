"""Bounded, redirect-free standard-library HTTP transport."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from http.client import HTTPException
from typing import IO, Literal, Never, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from adaptorch_client.config import ClientConfig
from adaptorch_client.errors import AdaptOrchAPIError
from adaptorch_client.models import JSONMapping, JSONValue

_MAX_REQUEST_BYTES = 8 * 1024 * 1024
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_ERROR_CODE_LENGTH = 100
_MAX_ERROR_MESSAGE_LENGTH = 500


def _reject_json_constant(_value: str) -> Never:
    raise ValueError("non-finite JSON number")


def _parse_finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


class _ReadableResponse(Protocol):
    headers: Message

    def read(self, amount: int = -1) -> bytes: ...


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
    headers: Mapping[str, str] | None = None


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
                if name.lower() not in {"authorization", "x-api-key"}
            },
            **self._config.auth_headers,
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        request = Request(
            f"{self._config.api_url}{spec.path}",
            data=body,
            headers=headers,
            method=spec.method,
        )
        try:
            with build_opener(_NoRedirectHandler()).open(
                request,
                timeout=self._config.timeout_seconds,
            ) as response:
                return self._decode_mapping(self._read_bounded(response))
        except HTTPError as error:
            raise self._from_http_error(error) from None
        except (HTTPException, URLError, TimeoutError, OSError):
            raise AdaptOrchAPIError("AdaptOrch network request failed") from None

    @staticmethod
    def _encode_payload(payload: Mapping[str, JSONValue] | None) -> bytes | None:
        if payload is None:
            return None
        try:
            encoded = json.dumps(
                dict(payload),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
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
            decoded: JSONValue = json.loads(
                body,
                parse_constant=_reject_json_constant,
                parse_float=_parse_finite_float,
            )
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise AdaptOrchAPIError("AdaptOrch returned invalid JSON") from None
        if not isinstance(decoded, dict):
            raise AdaptOrchAPIError("AdaptOrch returned a non-object JSON response")
        return decoded

    def _from_http_error(self, error: HTTPError) -> AdaptOrchAPIError:
        try:
            body = self._read_bounded(error)
            decoded = self._decode_mapping(body)
        except AdaptOrchAPIError:
            return AdaptOrchAPIError(
                f"AdaptOrch API request failed with HTTP {error.code}",
                status_code=error.code,
            )

        error_value = decoded.get("error")
        if not isinstance(error_value, dict):
            return AdaptOrchAPIError(
                f"AdaptOrch API request failed with HTTP {error.code}",
                status_code=error.code,
            )

        code_value = error_value.get("code")
        message_value = error_value.get("message")
        code = (
            self._sanitize(code_value, _MAX_ERROR_CODE_LENGTH)
            if isinstance(code_value, str)
            else None
        )
        message = (
            self._sanitize(message_value, _MAX_ERROR_MESSAGE_LENGTH)
            if isinstance(message_value, str)
            else "request failed"
        )
        prefix = f"AdaptOrch API error {code}" if code else "AdaptOrch API error"
        return AdaptOrchAPIError(
            f"{prefix}: {message}",
            status_code=error.code,
            code=code,
        )

    def _sanitize(self, value: str, limit: int) -> str:
        redacted = value.replace(self._config.api_key, "[redacted]")
        printable = "".join(character if character.isprintable() else " " for character in redacted)
        return printable[:limit]
