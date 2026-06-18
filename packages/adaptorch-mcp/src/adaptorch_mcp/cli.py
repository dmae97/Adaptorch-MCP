from __future__ import annotations

import sys
from collections.abc import Sequence

_MISSING_ADAPTORCH_MESSAGE = (
    "adaptorch-mcp requires AdaptOrch. Install with: "
    "pip install 'adaptorch[api] @ git+https://github.com/dmae97/adaptorch.git'"
)


def main(argv: Sequence[str] | None = None) -> int:
    """Delegate the public console script to the canonical AdaptOrch MCP server."""
    try:
        from adaptorch.mcp_server import main as adaptorch_mcp_main
    except ModuleNotFoundError as exc:
        if exc.name == "adaptorch":
            print(_MISSING_ADAPTORCH_MESSAGE, file=sys.stderr)
            return 2
        raise

    forwarded_argv = list(argv) if argv is not None else None
    return int(adaptorch_mcp_main(forwarded_argv))
