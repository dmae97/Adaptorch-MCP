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
_MAX_LINE_BYTES = 8 * 1024 * 1024
_READ_CHUNK_BYTES = 65_536
_SENSITIVE_ENV_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "AUTH")
_REDACTION_LABEL = "[redacted]"

JsonObject = dict[str, Any]


class MCPStdioSmokeError(RuntimeError):
    """Raised when a local stdio MCP smoke test fails."""


def _jsonrpc_message(message_id: int, method: str, params: Mapping[str, Any]) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": message_id, "method": method, "params": dict(params)},
        separators=(",", ":"),
    )


class _LineReader:
    """Newline-framed reads straight from the pipe descriptor.

    A buffered text reader can hold the second response in its own buffer while
    ``select`` waits on an empty pipe. That stalls whenever the server (or an SSH
    session in front of it) keeps stdout open after answering, so lines are split
    here and the pipe is only polled when no complete line is buffered.
    """

    def __init__(self, stream: IO[bytes]) -> None:
        self._fd = stream.fileno()
        self._buffer = bytearray()
        self._eof = False

    def read_object(self, *, timeout_seconds: float) -> JsonObject:
        deadline = time.monotonic() + timeout_seconds
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0 and self._eof and self._buffer:
                newline = len(self._buffer)
            if newline >= 0:
                line = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                if line.strip():
                    return _decode_json_line(line)
                continue
            if self._eof:
                raise MCPStdioSmokeError("MCP server stdout closed before a response was read")
            if len(self._buffer) > _MAX_LINE_BYTES:
                raise MCPStdioSmokeError("MCP server response line exceeds 8 MiB")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._wait_readable(remaining):
                raise MCPStdioSmokeError(
                    f"timed out waiting for MCP response after {timeout_seconds}s"
                )
            chunk = os.read(self._fd, _READ_CHUNK_BYTES)
            if chunk:
                self._buffer += chunk
            else:
                self._eof = True

    def _wait_readable(self, timeout_seconds: float) -> bool:
        selector = selectors.DefaultSelector()
        selector.register(self._fd, selectors.EVENT_READ)
        try:
            return bool(selector.select(timeout_seconds))
        finally:
            selector.close()


def _decode_json_line(line: bytes) -> JsonObject:
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        # The line itself is not echoed: a login script may print anything.
        raise MCPStdioSmokeError(
            "MCP server returned non-JSON stdout; stdout must carry only JSON-RPC "
            "(over SSH use `ssh -T` and keep remote login scripts silent)"
        ) from exc
    if not isinstance(payload, dict):
        raise MCPStdioSmokeError("MCP server response must be a JSON object")
    return cast(JsonObject, payload)


def _sensitive_env_values(env: Mapping[str, str]) -> tuple[str, ...]:
    """Return non-empty sensitive env values that must not appear in smoke output."""
    values: list[str] = []
    for name, value in env.items():
        if len(value) < 4:
            continue
        if any(marker in name.upper() for marker in _SENSITIVE_ENV_MARKERS):
            values.append(value)
    return tuple(dict.fromkeys(values))


def _redact_sensitive_text(text: str, sensitive_values: Collection[str]) -> str:
    redacted = text
    for value in sensitive_values:
        redacted = redacted.replace(value, _REDACTION_LABEL)
    return redacted


def _format_jsonrpc_error(error: Any, sensitive_values: Collection[str]) -> str:
    try:
        rendered = json.dumps(error, sort_keys=True)
    except TypeError:
        rendered = str(error)
    return _redact_sensitive_text(rendered, sensitive_values)


def _shutdown_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _collect_stderr(
    process: subprocess.Popen[bytes],
    sensitive_values: Collection[str],
) -> str:
    stderr = process.stderr
    if stderr is None:
        return ""
    try:
        text = stderr.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return _redact_sensitive_text(text[-4000:], sensitive_values)


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

    process_env = dict(env) if env is not None else None
    sensitive_values = _sensitive_env_values(process_env if process_env is not None else os.environ)
    started_at = time.monotonic()
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=process_env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    reader = _LineReader(process.stdout)

    try:
        requests = (
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
            + _jsonrpc_message(2, "tools/list", {})
            + "\n"
        )
        try:
            process.stdin.write(requests.encode("utf-8"))
            process.stdin.flush()
            process.stdin.close()
        except BrokenPipeError as exc:
            raise MCPStdioSmokeError("MCP server closed stdin before reading requests") from exc

        responses: dict[int, JsonObject] = {}
        deadline = started_at + timeout_seconds
        while len(responses) < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPStdioSmokeError(
                    f"timed out waiting for MCP responses after {timeout_seconds}s"
                )
            response = reader.read_object(timeout_seconds=remaining)
            response_id = response.get("id")
            if isinstance(response_id, int):
                responses[response_id] = response

        initialize = responses[1]
        tools_response = responses[2]
        if "error" in initialize:
            error = _format_jsonrpc_error(initialize["error"], sensitive_values)
            raise MCPStdioSmokeError(f"initialize failed: {error}")
        if "error" in tools_response:
            error = _format_jsonrpc_error(tools_response["error"], sensitive_values)
            raise MCPStdioSmokeError(f"tools/list failed: {error}")

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
        _shutdown_process(process)
        stderr = _collect_stderr(process, sensitive_values)
        if stderr:
            raise MCPStdioSmokeError(f"MCP process exited with stderr: {stderr}") from exc
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
        sensitive_values = _sensitive_env_values(env)
        error = _redact_sensitive_text(str(exc), sensitive_values)
        print(json.dumps({"ok": False, "error": error}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
