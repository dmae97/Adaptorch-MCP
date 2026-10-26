"""Persistent HTTP/1.1 connections for urllib openers.

The standard ``urllib`` handlers open a new TCP connection, and for HTTPS a new
TLS handshake with a freshly loaded CA store, for every request. Polling a run
therefore paid a full handshake per read. These handlers keep the stock
``http_open``/``https_open`` entry points and only replace ``do_open``, so an
opener built from them still has no redirect, proxy or retry handlers unless the
caller adds them.

Reuse rules:

* Only ``GET`` and ``HEAD`` take an idle connection. Every other method opens a
  fresh one, so a submission or cancellation is never written to a connection the
  peer may already have closed, and is never sent twice.
* An idle connection is reused only within ``IDLE_SECONDS`` and only while its
  socket shows no pending EOF or unexpected bytes.
* If a reused connection still turns out closed before any response arrives, the
  read is sent once more on a fresh connection. A timeout is never re-sent.
* A response returns its connection to the pool only when its body was read to
  the end and the server did not ask to close.
"""

from __future__ import annotations

import http.client
import select
import socket
import ssl
import threading
import time
from collections.abc import Callable
from typing import Final
from urllib.error import URLError
from urllib.request import HTTPHandler, HTTPSHandler, Request

__all__ = [
    "IDLE_SECONDS",
    "MAX_IDLE_PER_HOST",
    "KeepAliveHTTPHandler",
    "KeepAliveHTTPSHandler",
    "create_tls_context",
    "keepalive_handlers",
]

# uvicorn closes idle keep-alive connections after 5 s by default; staying below
# that avoids racing the server's own close on the next read.
IDLE_SECONDS: Final = 4.0
MAX_IDLE_PER_HOST: Final = 4
_REPLAYABLE_METHODS: Final = frozenset({"GET", "HEAD"})
# RemoteDisconnected subclasses ConnectionResetError; TimeoutError is deliberately absent.
_STALE_ERRORS: Final = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)

_Release = Callable[[bool], None]


def create_tls_context() -> ssl.SSLContext:
    """Return a verifying client context that refuses anything older than TLS 1.2."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class _PooledResponse(http.client.HTTPResponse):
    """Hand the connection back on close, but only after a complete body."""

    _adaptorch_release: _Release | None = None

    def close(self) -> None:
        # read() drops fp once Content-Length or the final chunk is consumed. It also
        # drops it on an early EOF, which leaves a positive length still owed.
        reusable = self.fp is None and not self.will_close and not self.length
        try:
            super().close()
        finally:
            release, self._adaptorch_release = self._adaptorch_release, None
            if release is not None:
                release(reusable)


class _HTTPConnection(http.client.HTTPConnection):
    response_class = _PooledResponse


class _HTTPSConnection(http.client.HTTPSConnection):
    response_class = _PooledResponse


def _apply_timeout(connection: http.client.HTTPConnection, timeout: object) -> None:
    value = timeout if isinstance(timeout, int | float) else socket.getdefaulttimeout()
    connection.timeout = value
    if connection.sock is not None:
        connection.sock.settimeout(value)


def _quickack(connection: http.client.HTTPConnection) -> None:
    """Acknowledge response segments at once where the kernel supports it (Linux).

    On a persistent connection a server that leaves Nagle on writes the headers,
    then holds the body until they are acknowledged, while the client's delayed
    ACK waits up to 40 ms. ``http.client`` already disables Nagle on our side; the
    flag is reset by the kernel, so it is set again before every response.
    """
    option = getattr(socket, "TCP_QUICKACK", None)
    if option is None or connection.sock is None:
        return
    try:
        connection.sock.setsockopt(socket.IPPROTO_TCP, option, 1)
    except OSError:
        return


def _dropped(connection: http.client.HTTPConnection) -> bool:
    """An idle socket that is readable has seen EOF or bytes nobody asked for."""
    sock = connection.sock
    if sock is None:
        return True
    try:
        if hasattr(select, "poll"):
            poller = select.poll()
            poller.register(sock, select.POLLIN | select.POLLERR | select.POLLHUP)
            return bool(poller.poll(0))
        readable, _, _ = select.select([sock], [], [], 0)
        return bool(readable)
    except (OSError, ValueError):
        return True


class _ConnectionPool:
    """Thread-safe LIFO of idle connections, keyed by ``scheme://host:port``."""

    def __init__(self, tls_context: ssl.SSLContext | None) -> None:
        # Reentrant: a response collected by GC closes, and so checks in, from
        # whatever frame happens to allocate, possibly one already holding the lock.
        self._lock = threading.RLock()
        self._idle: dict[str, list[tuple[http.client.HTTPConnection, float]]] = {}
        self._tls_context = tls_context
        self._closed = False

    def _context(self) -> ssl.SSLContext:
        with self._lock:
            if self._tls_context is None:
                # Loading the CA store costs tens of milliseconds; pay it once.
                self._tls_context = create_tls_context()
            return self._tls_context

    def _open(self, scheme: str, host: str, timeout: object) -> http.client.HTTPConnection:
        connection: http.client.HTTPConnection
        if scheme == "https":
            connection = _HTTPSConnection(host, context=self._context())
        else:
            connection = _HTTPConnection(host)
        _apply_timeout(connection, timeout)
        return connection

    def checkout(
        self, scheme: str, host: str, timeout: object, *, reuse: bool
    ) -> tuple[http.client.HTTPConnection, bool]:
        key = f"{scheme}://{host}"
        while reuse:
            with self._lock:
                stack = self._idle.get(key)
                entry = stack.pop() if stack else None
            if entry is None:
                break
            connection, idle_since = entry
            if time.monotonic() - idle_since <= IDLE_SECONDS and not _dropped(connection):
                _apply_timeout(connection, timeout)
                return connection, True
            connection.close()
        return self._open(scheme, host, timeout), False

    def checkin(self, scheme: str, host: str, connection: http.client.HTTPConnection) -> None:
        key = f"{scheme}://{host}"
        with self._lock:
            stack = self._idle.setdefault(key, [])
            if not self._closed and connection.sock is not None and len(stack) < MAX_IDLE_PER_HOST:
                stack.append((connection, time.monotonic()))
                return
        connection.close()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            idle, self._idle = self._idle, {}
        for stack in idle.values():
            for connection, _ in stack:
                connection.close()


class _KeepAliveMixin:
    _scheme: str
    _pool: _ConnectionPool

    def _exchange(self, req: Request) -> http.client.HTTPResponse:
        host = req.host
        if not host:
            raise URLError("no host given")
        headers = dict(req.unredirected_hdrs)
        headers.update({k: v for k, v in req.headers.items() if k not in headers})
        headers = {name.title(): value for name, value in headers.items()}
        method = req.get_method()
        replayable = method in _REPLAYABLE_METHODS
        for attempt in (0, 1):
            connection, reused = self._pool.checkout(
                self._scheme, host, req.timeout, reuse=replayable
            )
            resend = reused and attempt == 0
            try:
                connection.request(
                    method,
                    req.selector,
                    req.data,
                    headers,
                    encode_chunked=req.has_header("Transfer-encoding"),
                )
            except OSError as error:
                connection.close()
                if resend and isinstance(error, _STALE_ERRORS):
                    continue
                raise URLError(error) from None
            except BaseException:
                connection.close()
                raise
            _quickack(connection)
            try:
                response = connection.getresponse()
            except BaseException as error:
                connection.close()
                if resend and isinstance(error, _STALE_ERRORS):
                    continue
                raise
            if not isinstance(response, _PooledResponse):
                connection.close()
                raise http.client.HTTPException("unexpected response type")
            response.url = req.get_full_url()
            response.msg = response.reason  # type: ignore[assignment]
            response._adaptorch_release = self._releaser(host, connection)
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    def _releaser(self, host: str, connection: http.client.HTTPConnection) -> _Release:
        def release(reusable: bool) -> None:
            if reusable:
                self._pool.checkin(self._scheme, host, connection)
            else:
                connection.close()

        return release


class KeepAliveHTTPHandler(_KeepAliveMixin, HTTPHandler):
    """``HTTPHandler`` whose connections persist between requests."""

    def __init__(self, pool: _ConnectionPool | None = None) -> None:
        super().__init__()
        self._scheme = "http"
        self._pool = pool if pool is not None else _ConnectionPool(None)

    def do_open(
        self, http_class: object, req: Request, **http_conn_args: object
    ) -> http.client.HTTPResponse:
        return self._exchange(req)

    def close(self) -> None:
        self._pool.close()


class KeepAliveHTTPSHandler(_KeepAliveMixin, HTTPSHandler):
    """``HTTPSHandler`` whose TLS sessions persist between requests."""

    def __init__(
        self, pool: _ConnectionPool | None = None, context: ssl.SSLContext | None = None
    ) -> None:
        super().__init__(context=context)
        self._scheme = "https"
        self._pool = pool if pool is not None else _ConnectionPool(context)

    def do_open(
        self, http_class: object, req: Request, **http_conn_args: object
    ) -> http.client.HTTPResponse:
        return self._exchange(req)

    def close(self) -> None:
        self._pool.close()


def keepalive_handlers(
    context: ssl.SSLContext | None = None,
) -> tuple[KeepAliveHTTPHandler, KeepAliveHTTPSHandler]:
    """Return an HTTP and HTTPS handler pair sharing one connection pool.

    ``context`` defaults to :func:`create_tls_context`, built on first HTTPS use.
    Closing either handler closes the shared pool.
    """
    pool = _ConnectionPool(context)
    return KeepAliveHTTPHandler(pool), KeepAliveHTTPSHandler(pool, context)
