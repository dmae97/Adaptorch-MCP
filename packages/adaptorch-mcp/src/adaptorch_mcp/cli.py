"""Unambiguous public launcher; help never imports or contacts private core."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Never

from adaptorch_mcp import __version__
from adaptorch_mcp.bridge import Bridge
from adaptorch_mcp.config import from_environment
from adaptorch_mcp.protocol import serve


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # Argparse errors otherwise echo invalid option values, potentially credentials.
        del message
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid CLI options. Use --help; 0.6 supports remote stdio only.\n")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        prog="adaptorch-mcp-client",
        description="AdaptOrch 0.6 remote-only stdio client. Local engine/full/HTTP unsupported.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--base-url", help="HTTPS origin; authenticated requests use POST /mcp")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Bounded request timeout, seconds (0 < timeout <= 300)",
    )
    parser.add_argument("--transport", choices=["stdio"], default="stdio")
    parser.add_argument(
        "--stdio-framing", choices=["line", "newline", "content-length"], default="line"
    )
    parser.add_argument(
        "--allow-loopback-http",
        action="store_true",
        help="Development only: permit exact loopback HTTP origin",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        config = from_environment(
            os.environ,
            base_url=args.base_url,
            timeout_seconds=args.timeout,
            allow_loopback_http=args.allow_loopback_http,
        )
    except ValueError as exc:
        # Every configuration error is owned by the public validators and contains no values.
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    try:
        framing = "line" if args.stdio_framing == "newline" else args.stdio_framing
        return serve(Bridge(config), sys.stdin.buffer, sys.stdout.buffer, framing)
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    except Exception:
        # Last boundary: raw exception text is never a protocol response or log message.
        print(
            "Client stopped after an internal protocol failure; no automatic retry occurred.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
