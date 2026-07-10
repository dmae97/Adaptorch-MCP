from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _load_runtime_app_factory() -> Callable[[], Any]:
    from adaptorch_mcp.runtime import create_hardened_http_app_from_env

    return create_hardened_http_app_from_env


def create_default_mcp_http_app() -> Any:
    """Return the canonical AdaptOrch HTTP app behind hardened wrapper policy."""
    return _load_runtime_app_factory()()
