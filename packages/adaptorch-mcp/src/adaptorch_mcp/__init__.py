from __future__ import annotations

from typing import Any

__version__ = "0.5.2"

__all__ = ["__version__", "collect_diagnostics", "create_default_mcp_http_app", "main"]


def __getattr__(name: str) -> Any:
    """Keep connection helpers importable without installing the private engine."""
    if name == "main":
        from adaptorch_mcp.cli import main

        return main
    if name == "collect_diagnostics":
        from adaptorch_mcp.diagnostics import collect_diagnostics

        return collect_diagnostics
    if name == "create_default_mcp_http_app":
        from adaptorch_mcp.server import create_default_mcp_http_app

        return create_default_mcp_http_app
    raise AttributeError(name)
