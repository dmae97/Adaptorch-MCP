"""Single-attempt authenticated POST /mcp. No redirects, proxies, cookies or REST fallback."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException, HTTPResponse, HTTPSConnection
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request

from adaptorch_mcp.config import BridgeConfig
from adaptorch_mcp.response_json import MAX_RESPONSE_BYTES, decode_response_text

MAX_REQUEST_BYTES = 1024 * 1024


class TransportFailure(Exception):
    """Fixed, secret-free transport classification; write outcome may be unknown."""

    def __init__(self, reason: str, status: int | None = None, *, sent: bool = True) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.sent = sent


class Transport(Protocol):
    def request(self, message: Mapping[str, Any], *, submit: bool = False) -> dict[str, Any]: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise TransportFailure("redirect_blocked", code)


class HTTPTransport:
    def __init__(
        self,
        config: BridgeConfig,
        *,
        opener: OpenerDirector | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._opener = opener
        self._clock = clock
        self._disabled = False

    @contextmanager
    def _open_native(self, request: Request, deadline: float) -> Iterator[HTTPResponse]:
        """Own and close this request's socket at its deadline after DNS/connect.

        DNS resolution is OS-governed and cannot be forcibly interrupted by stdlib.
        The synchronous process cannot accumulate unresolved workers or later replay writes.
        """
        parsed = urlsplit(self._config.client.api_url)
        connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        connection = connection_type(
            parsed.hostname or "", port=parsed.port, timeout=self._config.client.timeout_seconds
        )
        watchdog: threading.Timer | None = None
        response: HTTPResponse | None = None
        try:
            connection.connect()
            remaining = deadline - self._clock()
            if remaining <= 0 or connection.sock is None:
                raise TransportFailure("deadline", sent=False)
            owned_socket = connection.sock
            owned_socket.settimeout(remaining)

            def abort() -> None:
                try:
                    owned_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                owned_socket.close()

            watchdog = threading.Timer(remaining, abort)
            watchdog.daemon = True
            watchdog.start()
            connection.request(
                "POST", "/mcp", body=request.data, headers=dict(request.header_items())
            )
            response = connection.getresponse()
            yield response
        finally:
            if watchdog is not None:
                watchdog.cancel()
                watchdog.join(timeout=1.0)
                if watchdog.is_alive():
                    self._disabled = True
            if response is not None:
                response.close()
            connection.close()

    def request(self, message: Mapping[str, Any], *, submit: bool = False) -> dict[str, Any]:
        if self._disabled:
            raise TransportFailure("transport_disabled", sent=False)
        params = message.get("params")
        permitted = (
            message.get("method") == "tools/call"
            and isinstance(params, Mapping)
            and params.get("name") == "adaptorch_run"
            and isinstance(params.get("arguments"), Mapping)
            and "resume_run_id" not in params["arguments"]
        )
        if submit and not permitted:
            raise TransportFailure("provider_boundary", sent=False)
        try:
            body = json.dumps(message, ensure_ascii=True, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, RecursionError):
            raise TransportFailure("invalid_request", sent=False) from None
        if len(body) > MAX_REQUEST_BYTES:
            raise TransportFailure("request_too_large", sent=False)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **self._config.client.auth_headers,
        }
        if submit and self._config.provider is not None:
            headers.update(self._config.provider.headers)
        request = Request(
            self._config.client.api_url + "/mcp", data=body, headers=headers, method="POST"
        )
        deadline = self._clock() + self._config.client.timeout_seconds
        try:
            context = (
                self._opener.open(request, timeout=self._config.client.timeout_seconds)
                if self._opener is not None
                else self._open_native(request, deadline)
            )
            with context as response:
                status = response.status
                if status != 200:
                    raise TransportFailure(
                        "redirect_blocked" if 300 <= status < 400 else "http_status", status
                    )
                media = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if media != "application/json":
                    raise TransportFailure("protocol")
                encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
                if encoding not in {"", "identity"}:
                    raise TransportFailure("protocol")
                raw_length = response.headers.get("Content-Length")
                if raw_length is not None:
                    if (
                        len(raw_length) > 20
                        or not raw_length.isascii()
                        or not raw_length.isdecimal()
                        or int(raw_length) > MAX_RESPONSE_BYTES
                    ):
                        raise TransportFailure("response_too_large")
                chunks: list[bytes] = []
                size = 0
                while True:
                    if self._clock() > deadline:
                        raise TransportFailure("deadline")
                    reader = getattr(response, "read1", response.read)
                    chunk = reader(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise TransportFailure("response_too_large")
                    chunks.append(chunk)
                if self._clock() > deadline:
                    raise TransportFailure("deadline")
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise TransportFailure(
                "redirect_blocked" if 300 <= status < 400 else "http_status", status
            ) from None
        except (TimeoutError, OSError, URLError, HTTPException):
            reason = "deadline" if self._clock() >= deadline else "network"
            raise TransportFailure(reason) from None
        try:
            decoded = decode_response_text(b"".join(chunks).decode("utf-8"))
        except UnicodeError:
            decoded = None
        if decoded is None or decoded.get("jsonrpc") != "2.0":
            raise TransportFailure("protocol")
        expected_id = message.get("id")
        if (
            type(decoded.get("id")) is not type(expected_id)
            or decoded.get("id") != expected_id
            or ("result" in decoded) == ("error" in decoded)
        ):
            raise TransportFailure("protocol")
        return decoded
