from __future__ import annotations

from typing import Any


def create_default_mcp_http_app() -> Any:
    """Return the canonical AdaptOrch MCP HTTP ASGI app.

    Importing lazily keeps this wrapper lightweight and lets users see a clear
    dependency error only when they actually start the server.
    """
    from adaptorch.mcp_server import create_default_mcp_http_app as factory

    return factory()
