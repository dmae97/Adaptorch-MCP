"""Bounded JSON-line and Content-Length stdio framing, with stdout reserved for RPC."""

from __future__ import annotations

import json
from typing import Any, BinaryIO

from adaptorch_mcp.bridge import Bridge
from adaptorch_mcp.response_json import decode_response_text
from adaptorch_mcp.transport import MAX_REQUEST_BYTES

MAX_HEADER_BYTES = 8192


class FramingError(Exception):
    pass


def read_message(stream: BinaryIO, framing: str) -> bytes | None:
    if framing == "line":
        line = stream.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            return None
        if len(line) > MAX_REQUEST_BYTES:
            raise FramingError
        return line
    total = 0
    length: int | None = None
    seen: set[str] = set()
    while True:
        line = stream.readline(MAX_HEADER_BYTES + 1)
        if not line:
            if total == 0:
                return None
            raise FramingError
        total += len(line)
        if total > MAX_HEADER_BYTES or not line.endswith(b"\r\n"):
            raise FramingError
        if line == b"\r\n":
            break
        try:
            key, value = line[:-2].decode("ascii").split(":", 1)
        except (ValueError, UnicodeError):
            raise FramingError from None
        key, value = key.lower(), value.strip()
        if key in seen or key not in {"content-length", "content-type"}:
            raise FramingError
        seen.add(key)
        if key == "content-length":
            if not value.isdecimal() or len(value) > 10:
                raise FramingError
            length = int(value)
        elif value.lower() not in {
            "application/json",
            "application/vscode-jsonrpc; charset=utf-8",
            "application/vscode-jsonrpc; charset=utf8",
        }:
            raise FramingError
    if length is None or not 1 <= length <= MAX_REQUEST_BYTES:
        raise FramingError
    body = stream.read(length)
    if len(body) != length:
        raise FramingError
    return body


def write_message(stream: BinaryIO, value: dict[str, Any], framing: str) -> None:
    body = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    if framing == "content-length":
        stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    else:
        stream.write(body + b"\n")
    stream.flush()


def serve(
    bridge: Bridge, input_stream: BinaryIO, output_stream: BinaryIO, framing: str = "line"
) -> int:
    while not bridge.exited:
        try:
            raw = read_message(input_stream, framing)
        except FramingError:
            write_message(
                output_stream,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Invalid or oversized frame"},
                },
                framing,
            )
            return 2  # Stop after desynchronization; never reinterpret a partial write request.
        if raw is None:
            return 0
        try:
            message = decode_response_text(raw.decode("utf-8"))
        except UnicodeError:
            message = None
        response: dict[str, Any] | None
        if message is None:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Invalid JSON object"},
            }
        else:
            response = bridge.handle_message(message)
        if response is not None:
            write_message(output_stream, response, framing)
    return 0
