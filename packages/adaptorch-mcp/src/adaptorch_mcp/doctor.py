from __future__ import annotations

import argparse
import importlib
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

from adaptorch_mcp.diagnostics import collect_diagnostics, format_diagnostics

_CONTROL_PLANE_TOKEN_ENV = "ADAPTORCH_CONTROL_PLANE_TOKEN"
_HOSTED_HINT_OPT_OUT_ENV = "ADAPTORCH_NO_HOSTED_HINT"


def _control_plane_token_set(payload: Mapping[str, Any]) -> bool:
    environment = payload.get("environment", {})
    tokens = environment.get("tokens", {}) if isinstance(environment, Mapping) else {}
    status = tokens.get(_CONTROL_PLANE_TOKEN_ENV, {}) if isinstance(tokens, Mapping) else {}
    return bool(status.get("set")) if isinstance(status, Mapping) else False


def hosted_pointer(payload: Mapping[str, Any], env: Mapping[str, str] | None = None) -> str | None:
    """One line pointing a token-less operator at the free hosted plan.

    Only when no control-plane token is configured, which is exactly when the
    doctor is answering "how do I connect". The sentence and its plan facts come
    from the engine's own `hosted_hint` module so no number is retyped here; an
    engine that predates it gets no pointer rather than a guessed one.
    """
    resolved_env = os.environ if env is None else env
    if resolved_env.get(_HOSTED_HINT_OPT_OUT_ENV, "").strip():
        return None
    if _control_plane_token_set(payload):
        return None
    # Resolved at runtime: the module arrived in engine 0.1.3, and the wrapper
    # supports every engine >= 0.1.0, so the import cannot be static.
    try:
        hosted_hint = importlib.import_module("adaptorch.hosted_hint")
    except ImportError:  # pragma: no cover - depends on the installed engine revision
        return None
    hint_text = getattr(hosted_hint, "hosted_hint_text", None)
    if not callable(hint_text):  # pragma: no cover - defensive against a partial engine
        return None
    return str(hint_text(medium="mcp-doctor"))


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
        pointer = hosted_pointer(payload)
        if pointer is not None:
            print(f"\nNo {_CONTROL_PLANE_TOKEN_ENV} set. {pointer}")

    ok = bool(payload.get("ok"))
    if args.strict:
        ok = ok and _control_plane_token_set(payload)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
