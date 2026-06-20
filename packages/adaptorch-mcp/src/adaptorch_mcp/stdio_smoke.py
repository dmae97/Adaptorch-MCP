from __future__ import annotations

import argparse
import json
import os
import selectors
import shlex
import subprocess
import time
from collections.abc import Collection, Mapping, Sequence
from typing import IO, Any, cast

from adaptorch_mcp.diagnostics import EXPECTED_CORE_TOOLS

_SMOKE_DEFAULT_BASE_URL = "http://127.0.0.1:8000"

JsonObject = dict[str, Any]


class MCPStdioSmokeError(RuntimeError):
    """Raised when a local stdio MCP smoke test fails."""


def _jsonrpc_message(message_id: int, method: str, params: Mapping[str, Any]) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": message_id, "method": method, "params": dict(params)},
        separators=(",", ":"),
    )


def _read_json_line(stdout: IO[str], *, timeout_seconds: float) -> JsonObject:
    selector = selectors.DefaultSelector()
    selector.register(stdout, selectors.EVENT_READ)
    try:
        if not selector.select(timeout_seconds):
            raise MCPStdioSmokeError(f"timed out waiting for MCP response after {timeout_seconds}s")
        line = stdout.readline()
    finally:
        selector.close()

    if not line:
        raise MCPStdioSmokeError("MCP server stdout closed before a response was read")
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise MCPStdioSmokeError("MCP server returned non-JSON stdout") from exc
    if not isinstance(payload, dict):
        raise MCPStdioSmokeError("MCP server response must be a JSON object")
    return cast(JsonObject, payload)


def _shutdown_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _collect_stderr(process: subprocess.Popen[str]) -> str:
    stderr = process.stderr
    if stderr is None:
        return ""
    try:
        return stderr.read()[-4000:]
    except OSError:
        return ""


def run_stdio_smoke(
    command: Sequence[str],
    *,
    timeout_seconds: float = 10.0,
    expected_tools: Collection[str] = EXPECTED_CORE_TOOLS,
    env: Mapping[str, str] | None = None,
) -> JsonObject:
    """Start an MCP stdio server and verify initialize + tools/list."""
    if not command:
        raise ValueError("command must not be empty")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    started_at = time.monotonic()
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(env) if env is not None else None,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        process.stdin.write(
            _jsonrpc_message(
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "adaptorch-mcp-smoke", "version": "0.1"},
                },
            )
            + "\n"
        )
        process.stdin.write(_jsonrpc_message(2, "tools/list", {}) + "\n")
        process.stdin.flush()
        process.stdin.close()

        responses: dict[int, JsonObject] = {}
        deadline = started_at + timeout_seconds
        while len(responses) < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPStdioSmokeError(
                    f"timed out waiting for MCP responses after {timeout_seconds}s"
                )
            response = _read_json_line(process.stdout, timeout_seconds=remaining)
            response_id = response.get("id")
            if isinstance(response_id, int):
                responses[response_id] = response

        initialize = responses[1]
        tools_response = responses[2]
        if "error" in initialize:
            raise MCPStdioSmokeError(f"initialize failed: {initialize['error']}")
        if "error" in tools_response:
            raise MCPStdioSmokeError(f"tools/list failed: {tools_response['error']}")

        result = tools_response.get("result", {})
        tools_raw = result.get("tools", []) if isinstance(result, Mapping) else []
        found_tool_names: list[str] = []
        for item in tools_raw:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name")
            if isinstance(name, str):
                found_tool_names.append(name)
        tool_names = sorted(found_tool_names)
        expected = sorted(expected_tools)
        missing = [name for name in expected if name not in tool_names]
        if missing:
            raise MCPStdioSmokeError(f"missing expected tools: {', '.join(missing)}")

        return {
            "ok": True,
            "tool_count": len(tool_names),
            "tools": tool_names,
            "protocolVersion": initialize.get("result", {}).get("protocolVersion")
            if isinstance(initialize.get("result"), Mapping)
            else None,
            "duration_ms": round((time.monotonic() - started_at) * 1000, 3),
        }
    except Exception as exc:
        if process.poll() is not None:
            stderr = _collect_stderr(process)
            if stderr:
                raise MCPStdioSmokeError(
                    f"MCP process exited with stderr: {stderr}"
                ) from exc
        raise
    finally:
        _shutdown_process(process)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test an AdaptOrch MCP stdio server")
    parser.add_argument(
        "--command",
        default="adaptorch-mcp",
        help="Command used to start the MCP server; shell-like quoting is supported",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("ADAPTORCH_CONTROL_PLANE_BASE_URL", _SMOKE_DEFAULT_BASE_URL),
        help="AdaptOrch control-plane or gateway URL",
    )
    parser.add_argument(
        "--api-token",
        default=os.getenv("ADAPTORCH_CONTROL_PLANE_TOKEN"),
        help="Control-plane token; defaults to ADAPTORCH_CONTROL_PLANE_TOKEN",
    )
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--expected-tool",
        action="append",
        default=None,
        help="Expected MCP tool name; may be repeated. Defaults to core AdaptOrch tools.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.api_token:
        raise SystemExit("--api-token or ADAPTORCH_CONTROL_PLANE_TOKEN is required")

    command = shlex.split(args.command) + [
        "--transport",
        "stdio",
        "--base-url",
        args.base_url,
        "--stdio-framing",
        "newline",
    ]
    env = os.environ.copy()
    env["ADAPTORCH_CONTROL_PLANE_TOKEN"] = args.api_token
    expected_tools = tuple(args.expected_tool) if args.expected_tool else EXPECTED_CORE_TOOLS
    try:
        payload = run_stdio_smoke(
            command,
            timeout_seconds=args.timeout_seconds,
            expected_tools=expected_tools,
            env=env,
        )
    except MCPStdioSmokeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
