"""Dependency-free stdio transport for the remote-only MCP facade."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, BinaryIO, Literal

from adaptorch_mcp.thin_remote import RemoteMCPServer

Framing = Literal["newline", "content-length"]
_MAX_PAYLOAD = 1024 * 1024


def read_message(stream: BinaryIO, *, framing: Framing = "newline") -> dict[str, Any] | None:
    if framing == "newline":
        line = stream.readline(_MAX_PAYLOAD + 2)
        if not line:
            return None
        if len(line) > _MAX_PAYLOAD + 1 or not line.endswith(b"\n"):
            raise ValueError("MCP payload exceeds the local limit")
        payload = line.strip()
    else:
        headers: dict[str, str] = {}
        for _ in range(64):
            line = stream.readline(4097)
            if len(line) > 4096:
                raise ValueError("MCP header is too large")
            if line in {b"\r\n", b"\n"}:
                break
            name, separator, value = line.decode("ascii").partition(":")
            if not separator:
                raise ValueError("invalid MCP header")
            headers[name.strip().lower()] = value.strip()
        else:
            raise ValueError("too many MCP headers")
        length = headers.get("content-length", "")
        if not length.isdigit() or int(length) > _MAX_PAYLOAD:
            raise ValueError("invalid MCP Content-Length")
        payload = stream.read(int(length))
        if len(payload) != int(length):
            raise ValueError("incomplete MCP payload")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("MCP message must be an object")
    return value


def write_message(
    stream: BinaryIO,
    message: Mapping[str, Any],
    *,
    framing: Framing = "newline",
) -> None:
    body = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode()
    if framing == "newline":
        stream.write(body + b"\n")
    else:
        stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    stream.flush()


def serve_stdio(
    server: RemoteMCPServer,
    *,
    framing: Framing = "newline",
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
) -> int:
    """Serve until EOF or exit; every opened remote transport is closed."""
    import sys

    source = sys.stdin.buffer if input_stream is None else input_stream
    destination = sys.stdout.buffer if output_stream is None else output_stream
    try:
        while True:
            try:
                message = read_message(source, framing=framing)
            except (ValueError, UnicodeError, json.JSONDecodeError):
                write_message(
                    destination,
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Invalid MCP message"},
                    },
                    framing=framing,
                )
                continue
            if message is None:
                return 0
            response = server.handle_message(message)
            if response is not None:
                write_message(destination, response, framing=framing)
            if message.get("method") == "exit":
                return 0
    finally:
        server.close()
