"""Authenticated loopback HTTP transport for the remote-only MCP facade."""

from __future__ import annotations

import asyncio
import hmac
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

try:
    from starlette.requests import Request
except ModuleNotFoundError:  # stdio-only installation
    Request = object  # type: ignore[misc,assignment]

from adaptorch_mcp import __version__
from adaptorch_mcp.thin_remote import RemoteMCPServer

_MAX_PAYLOAD = 1024 * 1024
_PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})


def _lifespan(server: RemoteMCPServer) -> Any:
    @asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[None]:
        yield
        server.close()

    return lifespan


def create_remote_http_app(*, server: RemoteMCPServer, auth_token: str) -> Any:
    from fastapi import Depends, FastAPI, Header, HTTPException
    from fastapi.responses import JSONResponse

    app = FastAPI(lifespan=_lifespan(server))

    def authorize(authorization: str | None = Header(default=None)) -> None:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token or not hmac.compare_digest(token, auth_token):
            raise HTTPException(status_code=401, detail="Unauthorized")

    def validate_protocol(
        version: str | None = Header(default=None, alias="MCP-Protocol-Version"),
    ) -> None:
        if version is not None and version not in _PROTOCOL_VERSIONS:
            raise HTTPException(status_code=400, detail="Unsupported MCP protocol version")

    @app.get("/mcp/health", dependencies=[Depends(authorize)])
    async def health() -> dict[str, Any]:
        return {"status": "ok", "transport": "remote", "server_version": __version__}

    @app.post("/mcp", dependencies=[Depends(authorize), Depends(validate_protocol)])
    async def rpc(request: Request) -> Any:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse({"error": "invalid_content_length"}, status_code=400)
            if declared_length > _MAX_PAYLOAD:
                return JSONResponse({"error": "payload_too_large"}, status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > _MAX_PAYLOAD:
                return JSONResponse({"error": "payload_too_large"}, status_code=413)
            body.extend(chunk)
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                },
                status_code=400,
            )
        if not isinstance(payload, dict):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                },
                status_code=400,
            )
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(server.handle_message, payload), 300
            )
        except TimeoutError:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {"code": -32603, "message": "request timed out"},
                },
                status_code=504,
            )
        if response is None:
            return JSONResponse({"accepted": True}, status_code=202)
        return JSONResponse(response)

    return app
