from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from urllib.parse import urlparse

_CONTROL_PLANE_BASE_URL_ENV = "ADAPTORCH_CONTROL_PLANE_BASE_URL"
_HOSTED_BASE_URL = "https://adaptorch.ai.kr"
_ALLOWED_CONTROL_PLANE_SCHEMES = frozenset({"http", "https"})

_MISSING_ADAPTORCH_MESSAGE = (
    "adaptorch-mcp requires AdaptOrch. Install with: "
    "pip install 'adaptorch[api] @ git+https://github.com/dmae97/adaptorch.git'"
)


def _validate_control_plane_base_url(value: str, *, source: str) -> str:
    """Return a stripped http(s) URL or raise for invalid control-plane input."""
    stripped = value.strip()
    parsed = urlparse(stripped)
    if parsed.scheme.lower() not in _ALLOWED_CONTROL_PLANE_SCHEMES or not parsed.netloc:
        raise ValueError(f"{source} must be an http(s) URL with a host")
    return stripped


def _normalize_env_base_url(value: str | None) -> str | None:
    """Normalize the optional base-url environment variable.

    Empty or whitespace-only values are treated as unset. Non-empty values must
    be syntactically valid HTTP(S) URLs so misconfiguration fails before the
    wrapper submits work to an unexpected control plane.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return _validate_control_plane_base_url(stripped, source=_CONTROL_PLANE_BASE_URL_ENV)


def _strip_empty_base_url_equals(argv: Sequence[str]) -> list[str]:
    """Drop empty equals-form base-url tokens so env/hosted defaults can apply."""
    return [arg for arg in argv if arg != "--base-url="]


def _has_base_url_flag(argv: Sequence[str]) -> bool:
    """Return whether argv already carries a non-empty explicit base-url flag."""
    return any(
        arg == "--base-url" or (arg.startswith("--base-url=") and arg != "--base-url=")
        for arg in argv
    )


def _with_hosted_base_url_default(argv: Sequence[str] | None) -> list[str] | None:
    """Resolve the public wrapper's AdaptOrch control-plane base URL.

    Precedence is deterministic:
    1. Explicit ``--base-url`` or ``--base-url=...`` in argv.
    2. ``ADAPTORCH_CONTROL_PLANE_BASE_URL`` when no explicit flag is present.
    3. Hosted fallback for user-facing installs.

    The canonical ``adaptorch.mcp_server`` keeps a localhost default for
    core/local development. The public ``adaptorch-mcp`` package is user-facing,
    so omitting both CLI and env configuration should still make runs visible in
    the hosted dashboard.
    """
    raw_forwarded = list(argv) if argv is not None else sys.argv[1:]
    forwarded = _strip_empty_base_url_equals(raw_forwarded)
    if _has_base_url_flag(forwarded):
        if argv is None and forwarded == raw_forwarded:
            return None
        return forwarded

    env_base_url = _normalize_env_base_url(os.getenv(_CONTROL_PLANE_BASE_URL_ENV))
    if env_base_url is not None:
        return ["--base-url", env_base_url, *forwarded]

    return ["--base-url", _HOSTED_BASE_URL, *forwarded]


def main(argv: Sequence[str] | None = None) -> int:
    """Delegate the public console script to the canonical AdaptOrch MCP server."""
    try:
        from adaptorch.mcp_server import main as adaptorch_mcp_main
    except ModuleNotFoundError as exc:
        if exc.name == "adaptorch":
            print(_MISSING_ADAPTORCH_MESSAGE, file=sys.stderr)
            return 2
        raise

    forwarded_argv = _with_hosted_base_url_default(argv)
    return int(adaptorch_mcp_main(forwarded_argv))
