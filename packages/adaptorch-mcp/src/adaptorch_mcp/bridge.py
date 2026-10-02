"""Remote-only MCP policy bridge. All lifecycle and metrics state is process-local."""

from __future__ import annotations

import copy
import json
import time
from collections import Counter, deque
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from adaptorch_client.provider import sanitize_error

from adaptorch_mcp import __version__
from adaptorch_mcp.config import BridgeConfig
from adaptorch_mcp.contract import (
    PROMPT_NAMES,
    PROTOCOL_VERSION,
    PROTOCOL_VERSIONS,
    RESOURCE_URIS,
    RUN_ID,
    TOOL_NAMES,
    tool_descriptors,
    validate_arguments,
)
from adaptorch_mcp.discovery_output import project_catalog
from adaptorch_mcp.output_schema import project_tool_output
from adaptorch_mcp.public_schema import ParentContractError
from adaptorch_mcp.response_json import decode_response_text
from adaptorch_mcp.transport import HTTPTransport, Transport, TransportFailure

_CAPABILITIES = {
    "tools": {"listChanged": False},
    "resources": {"subscribe": False, "listChanged": False},
    "prompts": {"listChanged": False},
}
_WRITE_TOOLS = {"adaptorch_run", "adaptorch_cancel_run"}


class InvalidParams(Exception):
    pass


class InvalidResult(Exception):
    pass


def _error(identifier: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}


def _result(identifier: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identifier, "result": value}


def _tool_result(
    value: Mapping[str, Any], *, error: bool = False, structured: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": [
            {"type": "text", "text": json.dumps(value, ensure_ascii=True, allow_nan=False)}
        ],
        "isError": error,
    }
    if structured and not error:
        result["structuredContent"] = dict(value)
    return result


def _fixed_failure(
    reason: str,
    *,
    write: bool,
    status: int | None = None,
    sent: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    if status == 429:
        text = "Tenant quota or rate limit reached; inspect account usage before retrying."
    elif status in {401, 403}:
        text = "Authentication refused; check the tenant key and explicit provider configuration."
    elif reason == "unsupported_recovery":
        text = "Idempotency and resume are unavailable on this hosted MCP contract."
    else:
        text = "Hosted response unavailable or invalid. A submitted run may still be active."
    payload: dict[str, Any] = {
        "error": "HOSTED_MCP_ERROR",
        "reason": reason,
        "message": text,
        "request_outcome": "not_sent" if not sent else "unknown" if write else "read_only",
        "new_run_safe": False,
        "automatic_retry": False,
        "next_action": "inspect_existing_runs_before_resubmitting" if write else "retry_read",
    }
    if status is not None:
        payload["status_code"] = status
    if run_id is not None:
        payload["run_id"] = run_id
    return _tool_result(payload, error=True)


def _closed_params(
    params: Any, allowed: set[str], required: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(params, dict) or set(params) - allowed or (required or set()) - set(params):
        raise InvalidParams
    return params


def _artifact_safe(value: Any) -> bool:
    if not isinstance(value, str) or not 0 < len(value) <= 4096:
        return False
    if any(not char.isprintable() for char in value) or "\\" in value:
        return False
    try:
        url = urlsplit(value)
        if url.username is not None or url.password is not None or url.fragment or url.query:
            return False
        if url.port == 0:
            return False
    except ValueError:
        return False
    if url.scheme not in {"https", "s3", "gs", "adaptorch"} or not url.netloc:
        return False
    if any(part in {".", ".."} for part in unquote(url.path).split("/")):
        return False
    return True


def _validate_artifacts(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"artifact_urls", "artifacts"}:
                references = list(item.values()) if isinstance(item, dict) else item
                if not isinstance(references, list) or not all(
                    _artifact_safe(v) for v in references
                ):
                    return False
            elif not _validate_artifacts(item):
                return False
    elif isinstance(value, list):
        return all(_validate_artifacts(item) for item in value)
    return True


def _bound_run_ids(value: Any, expected: str) -> bool:
    if isinstance(value, dict):
        if "run_id" in value and value["run_id"] is not None and value["run_id"] != expected:
            return False
        return all(_bound_run_ids(item, expected) for item in value.values())
    if isinstance(value, list):
        return all(_bound_run_ids(item, expected) for item in value)
    return True


def _restrict_recovery(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"recovery", "connector_recovery"} and isinstance(item, dict):
                for flag in ("new_run_safe", "replay_safe"):
                    if flag in item:
                        item[flag] = False
                if item.get("next_action") in {"resume_existing_run", "reuse_same_request_and_key"}:
                    item["next_action"] = "inspect_existing_runs_before_resubmitting"
            _restrict_recovery(item)
    elif isinstance(value, list):
        for item in value:
            _restrict_recovery(item)


class Bridge:
    def __init__(self, config: BridgeConfig, transport: Transport | None = None) -> None:
        self._config = config
        self._transport = transport if transport is not None else HTTPTransport(config)
        self._initialized = False
        self._shutdown = False
        self._exited = False
        self._tools: list[dict[str, Any]] = []
        self._counter = 0
        self._tool_calls = 0
        self._tool_errors = 0
        self._latencies: deque[float] = deque(maxlen=2048)
        self._statuses: Counter[str] = Counter()
        self._observed_tenant: str | None = None
        self._protocol_version = PROTOCOL_VERSION
        self._prompts_verified = False

    @property
    def exited(self) -> bool:
        return self._exited

    def _scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            return sanitize_error(value, self._config.secrets, max(1, len(value)))
        if isinstance(value, dict):
            return {self._scrub(key): self._scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._scrub(item) for item in value]
        return value

    def _upstream(
        self, method: str, params: Mapping[str, Any], *, submit: bool = False
    ) -> dict[str, Any]:
        self._counter += 1
        identifier = f"bridge-{self._counter}"
        response = self._transport.request(
            {"jsonrpc": "2.0", "id": identifier, "method": method, "params": dict(params)},
            submit=submit,
        )
        # Enforce here too: fake/plugin transports cannot waive the subject boundary.
        if (
            not isinstance(response, dict)
            or response.get("jsonrpc") != "2.0"
            or type(response.get("id")) is not str
            or response.get("id") != identifier
            or ("result" in response) == ("error" in response)
        ):
            raise InvalidResult
        return response

    def _initialize(self, params: Any) -> dict[str, Any]:
        if self._initialized or self._shutdown:
            raise InvalidParams
        checked = _closed_params(
            params,
            {"protocolVersion", "capabilities", "clientInfo"},
            {"protocolVersion", "capabilities", "clientInfo"},
        )
        if (
            not isinstance(checked["protocolVersion"], str)
            or not isinstance(checked["capabilities"], dict)
            or not isinstance(checked["clientInfo"], dict)
        ):
            raise InvalidParams
        requested = checked["protocolVersion"]
        self._protocol_version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSION
        response = self._upstream(
            "initialize",
            {
                "protocolVersion": self._protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "adaptorch-mcp-client", "version": __version__},
            },
        )
        result = response.get("result")
        if (
            not isinstance(result, dict)
            or result.get("protocolVersion") not in PROTOCOL_VERSIONS
            or not isinstance(result.get("serverInfo"), dict)
            or not isinstance(result.get("capabilities"), dict)
        ):
            raise InvalidResult
        self._protocol_version = result["protocolVersion"]
        tool_response = self._upstream("tools/list", {})
        tool_result = tool_response.get("result")
        if not isinstance(tool_result, dict) or "nextCursor" in tool_result:
            raise InvalidResult
        self._tools = tool_descriptors(tool_result.get("tools"))
        self._initialized = True
        return self._server_info()

    def _server_info(self) -> dict[str, Any]:
        return {
            "protocolVersion": self._protocol_version,
            "serverInfo": {"name": "adaptorch-mcp-client", "version": __version__},
            "capabilities": copy.deepcopy(_CAPABILITIES),
        }

    def _metrics(self) -> dict[str, Any]:
        values = sorted(self._latencies)

        def percentile(fraction: float) -> float:
            return (
                values[min(len(values) - 1, int((len(values) - 1) * fraction))] if values else 0.0
            )

        return {
            "tool_calls": self._tool_calls,
            "tool_errors": self._tool_errors,
            "p50_latency_ms": percentile(0.5),
            "p95_latency_ms": percentile(0.95),
            "notification_failures": 0,
            "status_counts": dict(self._statuses),
        }

    def _bind_tenant(self, decoded: Mapping[str, Any]) -> None:
        tenant = decoded.get("tenant_id")
        if tenant is None:
            return
        if not isinstance(tenant, str) or not tenant or len(tenant) > 256:
            raise InvalidResult
        if self._observed_tenant is not None and tenant != self._observed_tenant:
            raise InvalidResult
        self._observed_tenant = tenant

    def _call_tool(self, params: Any) -> dict[str, Any]:
        checked = _closed_params(params, {"name", "arguments"}, {"name"})
        name = checked["name"]
        if not isinstance(name, str) or name not in TOOL_NAMES:
            raise LookupError
        arguments = checked.get("arguments", {})
        descriptor = next(tool for tool in self._tools if tool["name"] == name)
        if isinstance(arguments, dict) and {"resume_run_id", "idempotency_key"} & set(arguments):
            return _fixed_failure("unsupported_recovery", write=False, sent=False)
        if not validate_arguments(name, arguments, descriptor["inputSchema"]):
            raise InvalidParams
        if name == "adaptorch_server_metrics":
            return _tool_result(self._metrics())
        expected_id = arguments.get("run_id")
        known_id = expected_id
        if expected_id is not None and any(
            secret in expected_id for secret in self._config.secrets
        ):
            raise InvalidParams
        try:
            response = self._upstream(
                "tools/call", {"name": name, "arguments": arguments}, submit=name == "adaptorch_run"
            )
            result = response.get("result")
            if "error" in response:
                return _fixed_failure("upstream_error", write=name in _WRITE_TOOLS, run_id=known_id)
            if not isinstance(result, dict) or type(result.get("isError", False)) is not bool:
                raise InvalidResult
            content = result.get("content")
            if (
                not isinstance(content, list)
                or len(content) != 1
                or not isinstance(content[0], dict)
                or content[0].get("type") != "text"
                or not isinstance(content[0].get("text"), str)
            ):
                raise InvalidResult
            decoded = decode_response_text(content[0]["text"])
            if decoded is None:
                raise InvalidResult
            if expected_id is not None and decoded.get("run_id", expected_id) != expected_id:
                raise InvalidResult
            observed_id = decoded.get("run_id")
            if (
                known_id is None
                and isinstance(observed_id, str)
                and RUN_ID.fullmatch(observed_id) is not None
                and not any(secret in observed_id for secret in self._config.secrets)
            ):
                known_id = observed_id
            self._bind_tenant(decoded)
            if result.get("isError", False):
                status = decoded.get("status_code")
                if type(status) is not int or not 100 <= status <= 599:
                    status = 429 if decoded.get("error") == "QUOTA_EXCEEDED" else None
                return _fixed_failure(
                    "upstream_error", write=name in _WRITE_TOOLS, status=status, run_id=known_id
                )
            projected = project_tool_output(name, decoded)
            if name == "adaptorch_get_artifacts" and (
                projected is None or not _validate_artifacts(projected)
            ):
                return _tool_result(
                    {
                        "error": "ARTIFACT_REFERENCES_UNAVAILABLE",
                        "message": "Safe hosted artifact references are unavailable.",
                        "run_id": known_id,
                        "artifact_status": "unavailable",
                        "request_outcome": "read_only",
                        "new_run_safe": False,
                        "automatic_retry": False,
                    },
                    error=True,
                )
            if projected is None or not _validate_artifacts(projected):
                raise InvalidResult
            subject = expected_id or projected.get("run_id")
            if subject is not None and not _bound_run_ids(projected, subject):
                raise InvalidResult
            if expected_id is not None and projected.get("run_id") != expected_id:
                raise InvalidResult
            if name == "adaptorch_list_runs":
                if len(projected["items"]) > arguments.get("limit", 20):
                    raise InvalidResult
                for item in projected["items"]:
                    if not _bound_run_ids(item, item["run_id"]):
                        raise InvalidResult
            if name == "adaptorch_capabilities":
                projected["server_capabilities"] = {
                    "tools": True,
                    "resources": True,
                    "prompts": True,
                    "logging": False,
                    "completions": False,
                    "verification_commands_enabled": False,
                    "idempotency": False,
                    "resume": False,
                }
            _restrict_recovery(projected)
            return _tool_result(self._scrub(projected), structured=name == "adaptorch_get_run")
        except (
            TransportFailure,
            InvalidResult,
            ValueError,
            TypeError,
            KeyError,
            RecursionError,
            OverflowError,
        ) as exc:
            if isinstance(exc, TransportFailure):
                return _fixed_failure(
                    exc.reason,
                    write=name in _WRITE_TOOLS,
                    status=exc.status,
                    sent=exc.sent,
                    run_id=known_id,
                )
            return _fixed_failure("protocol", write=name in _WRITE_TOOLS, run_id=known_id)

    def _read_resource(self, params: Any) -> dict[str, Any]:
        checked = _closed_params(params, {"uri"}, {"uri"})
        uri = checked["uri"]
        if uri not in RESOURCE_URIS:
            raise LookupError
        if uri == RESOURCE_URIS[0]:
            payload = {
                **self._server_info(),
                "initialized": self._initialized,
                "shutdownReceived": self._shutdown,
                "logLevel": "off",
            }
        else:
            response = self._upstream("resources/read", {"uri": uri})
            result = response.get("result", {})
            contents = result.get("contents") if isinstance(result, dict) else None
            if (
                not isinstance(contents, list)
                or len(contents) != 1
                or not isinstance(contents[0], dict)
                or contents[0].get("uri") != uri
                or contents[0].get("mimeType") != "application/json"
                or not isinstance(contents[0].get("text"), str)
            ):
                raise InvalidResult
            decoded = decode_response_text(contents[0]["text"])
            projected = project_catalog(decoded) if decoded is not None else None
            if projected is None:
                raise InvalidResult
            payload = self._scrub(projected)
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(payload, ensure_ascii=True),
                }
            ]
        }

    def _prompts(self, method: str, params: Any) -> dict[str, Any]:
        if method == "prompts/list":
            _closed_params(params, set())
            response = self._upstream(method, {})
            result = response.get("result")
            prompts = result.get("prompts") if isinstance(result, dict) else None
            if (
                not isinstance(result, dict)
                or not isinstance(prompts, list)
                or len(prompts) > 32
                or "nextCursor" in result
            ):
                raise InvalidResult
            names = [prompt.get("name") for prompt in prompts if isinstance(prompt, dict)]
            if any(names.count(name) != 1 for name in PROMPT_NAMES):
                raise InvalidResult
            self._prompts_verified = True
            return {
                "prompts": [
                    {
                        "name": PROMPT_NAMES[0],
                        "description": "Prepare a hosted task request.",
                        "arguments": [
                            {"name": "prompt", "required": True},
                            {"name": "context", "required": False},
                            {"name": "synthesis_mode", "required": False},
                        ],
                    },
                    {
                        "name": PROMPT_NAMES[1],
                        "description": "Prepare a run summary request.",
                        "arguments": [{"name": "run_id", "required": True}],
                    },
                ]
            }
        checked = _closed_params(params, {"name", "arguments"}, {"name"})
        name, arguments = checked["name"], checked.get("arguments", {})
        if name not in PROMPT_NAMES:
            raise LookupError
        required = {"prompt"} if name == PROMPT_NAMES[0] else {"run_id"}
        allowed = {"prompt", "context", "synthesis_mode"} if name == PROMPT_NAMES[0] else required
        _closed_params(arguments, allowed, required)
        if not all(
            isinstance(value, str) and 0 < len(value) <= 100000 for value in arguments.values()
        ):
            raise InvalidParams
        if "run_id" in arguments and RUN_ID.fullmatch(arguments["run_id"]) is None:
            raise InvalidParams
        if not self._prompts_verified:
            self._prompts("prompts/list", {})
        response = self._upstream(method, {"name": name, "arguments": arguments})
        result = response.get("result")
        messages = result.get("messages") if isinstance(result, dict) else None
        if not isinstance(messages, list) or not 1 <= len(messages) <= 8:
            raise InvalidResult
        safe_messages = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
                raise InvalidResult
            content = message.get("content")
            if (
                not isinstance(content, dict)
                or content.get("type") != "text"
                or not isinstance(content.get("text"), str)
                or len(content["text"]) > 100000
            ):
                raise InvalidResult
            safe_messages.append(
                {
                    "role": message["role"],
                    "content": {"type": "text", "text": self._scrub(content["text"])},
                }
            )
        return {"messages": safe_messages}

    def handle_message(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return _error(None, -32600, "Invalid Request")
        identifier = message.get("id")
        has_id = "id" in message
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
            or set(message) - {"jsonrpc", "id", "method", "params"}
            or (has_id and not (type(identifier) is int or isinstance(identifier, str)))
            or (
                isinstance(identifier, str)
                and (
                    len(identifier) > 256
                    or any(secret in identifier for secret in self._config.secrets)
                )
            )
        ):
            return _error(None, -32600, "Invalid Request")
        method = message["method"]
        # All notifications are local/no-op; cancellation cannot create a cloud write.
        if not has_id:
            if method == "exit":
                self._exited = True
            return None
        if self._shutdown and method != "exit":
            return _error(identifier, -32600, "Client session is shut down")
        params = message.get("params", {})
        started = time.monotonic()
        tool_call = method == "tools/call" and self._initialized
        if tool_call:
            self._tool_calls += 1
        try:
            if method == "initialize":
                value = self._initialize(params)
            elif method == "ping":
                _closed_params(params, set())
                value = {}
            elif method == "shutdown":
                _closed_params(params, set())
                self._shutdown = True
                value = None
            elif not self._initialized:
                return _error(identifier, -32002, "Initialize the client first")
            elif method == "tools/list":
                _closed_params(params, set())
                value = {"tools": copy.deepcopy(self._tools)}
            elif method == "tools/call":
                value = self._call_tool(params)
            elif method == "resources/list":
                _closed_params(params, set())
                value = {
                    "resources": [
                        {"uri": uri, "name": uri.rsplit("/", 1)[-1], "mimeType": "application/json"}
                        for uri in RESOURCE_URIS
                    ]
                }
            elif method == "resources/templates/list":
                _closed_params(params, set())
                value = {"resourceTemplates": []}
            elif method == "resources/read":
                value = self._read_resource(params)
            elif method in {"prompts/list", "prompts/get"}:
                value = self._prompts(method, params)
            else:
                raise LookupError
            response = _result(identifier, value)
        except InvalidParams:
            response = _error(identifier, -32602, "Invalid or unsupported arguments")
        except LookupError:
            response = _error(identifier, -32601, "Method not found")
        except (InvalidResult, ParentContractError):
            response = _error(identifier, -32603, "Hosted contract validation failed")
        except TransportFailure as exc:
            text = "Hosted request refused or unavailable"
            if exc.status in {401, 403, 429}:
                text += f" (HTTP {exc.status})"
            response = _error(identifier, -32001, text)
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
            response = _error(identifier, -32603, "Invalid hosted contract")
        if tool_call:
            failed = "error" in response or response.get("result", {}).get("isError", False)
            self._tool_errors += int(failed)
            self._statuses["error" if failed else "ok"] += 1
            self._latencies.append((time.monotonic() - started) * 1000)
        return cast(dict[str, Any], self._scrub(response))
