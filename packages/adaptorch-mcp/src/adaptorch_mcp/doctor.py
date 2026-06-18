from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from adaptorch_mcp.diagnostics import collect_diagnostics, format_diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect AdaptOrch MCP local runtime wiring")
    parser.add_argument("--json", action="store_true", help="Print redacted diagnostics as JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also require ADAPTORCH_CONTROL_PLANE_TOKEN to be set",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    payload = collect_diagnostics()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_diagnostics(payload))

    ok = bool(payload.get("ok"))
    if args.strict:
        environment = payload.get("environment", {})
        tokens = environment.get("tokens", {}) if isinstance(environment, dict) else {}
        token_status = tokens.get("ADAPTORCH_CONTROL_PLANE_TOKEN", {})
        ok = ok and bool(token_status.get("set")) if isinstance(token_status, dict) else False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
