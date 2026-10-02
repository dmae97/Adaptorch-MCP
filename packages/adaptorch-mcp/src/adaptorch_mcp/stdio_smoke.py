"""Explicit, read-only discovery smoke; invoking it requires a configured tenant."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Sequence

from adaptorch_mcp.contract import PROTOCOL_VERSION, TOOL_NAMES


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check stdio initialize and the exact nine-tool surface"
    )
    parser.add_argument("--command", default="adaptorch-mcp-client")
    parser.add_argument("--base-url", default="https://adaptorch.com")
    parser.add_argument("--allow-loopback-http", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "adaptorch-mcp-smoke", "version": "0.6.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        {"jsonrpc": "2.0", "method": "exit"},
    ]
    command = [args.command, "--base-url", args.base_url, "--timeout", "15"]
    if args.allow_loopback_http:
        command.append("--allow-loopback-http")
    try:
        completed = subprocess.run(
            command,
            input="".join(json.dumps(item) + "\n" for item in requests),
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            env=dict(os.environ),
        )
        lines = completed.stdout.splitlines()
        if len(lines) != 3 or len(completed.stdout) > 1024 * 1024:
            raise ValueError
        replies = [json.loads(line) for line in lines]
        names = [tool["name"] for tool in replies[1]["result"]["tools"]]
        ok = (
            completed.returncode == 0
            and replies[0]["id"] == 1
            and replies[1]["id"] == 2
            and replies[2]["id"] == 3
            and names == list(TOOL_NAMES)
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        ok = False
    print(
        json.dumps(
            {
                "ok": ok,
                "expectedToolCount": 9,
                "providerCallsAttempted": False,
                "hostedExecutionVerified": False,
            }
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
