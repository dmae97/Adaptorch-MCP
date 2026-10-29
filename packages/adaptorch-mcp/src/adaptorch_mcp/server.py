from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _load_runtime_app_factory() -> Callable[[], Any]:
    from adaptorch_mcp.thin_runtime import create_remote_http_app_from_env

    return create_remote_http_app_from_env


def create_default_mcp_http_app() -> Any:
    """Return the authenticated remote-client HTTP app, with no local engine."""
    return _load_runtime_app_factory()()
