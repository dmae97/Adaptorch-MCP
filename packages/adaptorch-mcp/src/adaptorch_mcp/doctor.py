"""Offline diagnostics only. No tenant/provider calls and no credential values."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from adaptorch_mcp import __version__
from adaptorch_mcp.config import from_environment
from adaptorch_mcp.contract import TOOL_NAMES


def collect_diagnostics(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    configured = bool(env.get("ADAPTORCH_CONTROL_PLANE_TOKEN") or env.get("ADAPTORCH_API_KEY"))
    checked_env = dict(env)
    if not configured:
        checked_env["ADAPTORCH_CONTROL_PLANE_TOKEN"] = "offline-diagnostic-placeholder"
    problems = []
    try:
        from_environment(checked_env)
    except ValueError as exc:
        problems.append(str(exc))
    return {
        "ok": not problems,
        "version": __version__,
        "python": sys.version.split()[0],
        "sdkVersion": importlib.metadata.version("adaptorch-client"),
        "transport": "stdio",
        "exposureProfile": "remote",
        "expectedTools": list(TOOL_NAMES),
        "expectedToolCount": len(TOOL_NAMES),
        "tenantCredentialConfigured": configured,
        "providerCredentialConfigured": bool(env.get("ADAPTORCH_MCP_PROVIDER_API_KEY")),
        "networkChecked": False,
        "hostedExecutionVerified": False,
        "metricsScope": "client-process",
        "idempotencySupported": False,
        "resumeSupported": False,
        "problems": problems,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline public MCP client diagnostics")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Require a configured tenant key")
    args = parser.parse_args(list(argv) if argv is not None else None)
    payload = collect_diagnostics()
    print(
        json.dumps(payload, indent=2)
        if args.json
        else "\n".join(f"{key}: {value}" for key, value in payload.items())
    )
    return 0 if payload["ok"] and (not args.strict or payload["tenantCredentialConfigured"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
