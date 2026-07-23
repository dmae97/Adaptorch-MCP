from __future__ import annotations

from adaptorch_mcp.cli import main
from adaptorch_mcp.diagnostics import collect_diagnostics
from adaptorch_mcp.server import create_default_mcp_http_app

__all__ = ["__version__", "collect_diagnostics", "create_default_mcp_http_app", "main"]

__version__ = "0.5.0"
