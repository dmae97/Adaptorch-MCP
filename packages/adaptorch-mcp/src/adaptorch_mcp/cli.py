from __future__ import annotations

import os
import sys
from collections.abc import Sequence

_HOSTED_BASE_URL = "https://adaptorch.ai.kr"

_MISSING_ADAPTORCH_MESSAGE = (
    "adaptorch-mcp requires AdaptOrch. Install with: "
    "pip install 'adaptorch[api] @ git+https://github.com/dmae97/adaptorch.git'"
)


def _with_hosted_base_url_default(argv: Sequence[str] | None) -> list[str] | None:
    """Default the public wrapper to the hosted AdaptOrch control plane.

    The canonical `adaptorch.mcp_server` keeps a localhost default for core/local
    development. The public `adaptorch-mcp` package is user-facing, so omitting
    `--base-url` should still make runs visible in the hosted dashboard.
    """
    forwarded = list(argv) if argv is not None else sys.argv[1:]
    if "--base-url" in forwarded or os.getenv("ADAPTORCH_CONTROL_PLANE_BASE_URL"):
        return forwarded if argv is not None else None
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
