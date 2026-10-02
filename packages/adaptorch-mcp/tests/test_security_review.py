"""Independent, socket-blocked adversarial checks for the public bridge.

These fixtures contain synthetic MCP data only. No production endpoint, provider,
private engine, browser, or live preview is used by this test module.
"""

from __future__ import annotations

import ast
import io
import json
import socket
import threading
import time
from copy import deepcopy
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request

import pytest
from adaptorch_client.config import ClientConfig
from adaptorch_client.provider import ProviderCredential

from adaptorch_mcp.bridge import Bridge
from adaptorch_mcp.config import BridgeConfig, from_environment
from adaptorch_mcp.contract import (
    PROMPT_NAMES,
    PROTOCOL_VERSION,
    RESOURCE_URIS,
    TOOL_NAMES,
    input_schema,
    tool_descriptors,
    validate_arguments,
)
from adaptorch_mcp.protocol import FramingError, read_message, serve
from adaptorch_mcp.public_schema import ParentContractError
from adaptorch_mcp.response_json import MAX_JSON_DEPTH, MAX_RESPONSE_BYTES, decode_response_text
from adaptorch_mcp.transport import HTTPTransport, TransportFailure, _NoRedirect


@pytest.fixture(autouse=True)
def deny_network():
    def denied(*_args, **_kwargs):
        raise AssertionError("Security review fixtures must not open network sockets")

    with (
        patch.object(socket.socket, "connect", denied),
        patch.object(socket.socket, "connect_ex", denied),
        patch.object(socket, "create_connection", denied),
        patch.object(socket, "getaddrinfo", denied),
    ):
        yield


@pytest.mark.parametrize(
    "raw",
    [
        '{"id": 1, "id": 2}',
        '{"x": {"credential": "first", "credential": "second"}}',
        '{"x": NaN}',
        '{"x": Infinity}',
        '{"x": -Infinity}',
        '{"x": 1e999}',
        "[]",
        "null",
        '"scalar"',
        "{",
        '{"x": "\\ud800"}',
    ],
)
def test_ambiguous_or_invalid_json_is_rejected(raw):
    assert decode_response_text(raw) is None


def test_json_byte_limit_counts_utf8_bytes():
    assert (
        decode_response_text(json.dumps({"x": "é" * (MAX_RESPONSE_BYTES // 2)}, ensure_ascii=False))
        is None
    )


def test_json_depth_is_bounded_before_decode():
    assert (
        decode_response_text('{"x":' + "[" * MAX_JSON_DEPTH + "0" + "]" * MAX_JSON_DEPTH + "}")
        is None
    )


def test_quoted_braces_are_not_json_depth():
    assert decode_response_text(json.dumps({"x": "{" * 1000 + '\\"' + "}" * 1000})) is not None


TENANT = "ado_synthetic_security_tenant_123"
PROVIDER = "synthetic_security_provider_456"
RUN_ID = "run-fixture-A"


def config(*, provider=True):
    return BridgeConfig(
        ClientConfig("https://bridge.invalid", TENANT, 5),
        ProviderCredential("openai", "synthetic-model", PROVIDER) if provider else None,
    )


def rpc(method="tools/call", *, request_id=17, name="adaptorch_run", arguments=None):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {
            "name": name,
            "arguments": {"prompt": "synthetic test"} if arguments is None else arguments,
        },
    }


class Response:
    def __init__(self, body, *, status=200, headers=None):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status
        self.headers = Message()
        for key, value in (headers or {"Content-Type": "application/json"}).items():
            self.headers[key] = value
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size):
        self.reads += 1
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


class Opener:
    def __init__(self, response=None, exception=None):
        self.response = response or Response({"jsonrpc": "2.0", "id": 17, "result": {}})
        self.exception = exception
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.exception:
            raise self.exception
        return self.response


def headers_of(opener):
    return {key.lower(): value for key, value in opener.requests[0][0].header_items()}


@pytest.mark.parametrize(
    "url",
    [
        "http://bridge.invalid",
        "https://user:secret@bridge.invalid",
        "https://bridge.invalid/mcp",
        "https://bridge.invalid?x=1",
        "https://bridge.invalid#x",
        "https://bridge.invalid:0",
        "https://bridge.invalid:65536",
        "https://bridge.invalid\\@other.invalid",
        " https://bridge.invalid",
        "https://bridge.invalid\n",
        "https://bridge.invalid\x00",
        "file:///tmp/secret",
    ],
)
def test_unsafe_origins_are_rejected(url):
    with pytest.raises(ValueError):
        BridgeConfig(ClientConfig(url, TENANT))


@pytest.mark.parametrize("url", ["http://localhost", "http://127.0.0.1", "http://[::1]"])
def test_loopback_http_requires_explicit_configuration(url):
    with pytest.raises(ValueError):
        BridgeConfig(ClientConfig(url, TENANT))
    assert BridgeConfig(ClientConfig(url, TENANT), allow_loopback_http=True)


@pytest.mark.parametrize("key", ["bad\r\nX-Tenant-ID: victim", " bad", "bad ", "", "x" * 4097])
def test_invalid_tenant_headers_fail_without_echo(key):
    with pytest.raises(ValueError) as exc:
        BridgeConfig(ClientConfig("https://bridge.invalid", key))
    if key:
        assert key not in str(exc.value)


def test_ambient_provider_keys_are_never_discovered():
    cfg = from_environment(
        {
            "ADAPTORCH_API_KEY": TENANT,
            "OPENAI_API_KEY": PROVIDER,
            "ANTHROPIC_API_KEY": PROVIDER,
            "HTTP_PROXY": "http://proxy.invalid",
        }
    )
    assert cfg.provider is None


@pytest.mark.parametrize(
    "env",
    [
        {"ADAPTORCH_MCP_EXPOSURE_PROFILE": "full"},
        {"ADAPTORCH_MCP_TRANSPORT": "http"},
        {"ADAPTORCH_MCP_PROVIDER": "auto"},
        {"ADAPTORCH_MCP_PROVIDER_API_KEY_COMMAND": "echo secret"},
        {"ADAPTORCH_MCP_PROVIDER_FALLBACK_API_KEY": PROVIDER},
        {"ADAPTORCH_MCP_ALLOW_INSECURE_CONTROL_PLANE": "1"},
    ],
)
def test_unsupported_configuration_is_not_silently_ignored(env):
    with pytest.raises(ValueError):
        from_environment({"ADAPTORCH_API_KEY": TENANT, **env})


def test_provider_headers_on_explicit_submit_only():
    opener = Opener()
    HTTPTransport(config(), opener=opener).request(rpc(), submit=True)
    headers = headers_of(opener)
    assert headers["x-api-key"] == TENANT
    assert headers["x-provider-key"] == PROVIDER
    assert headers["x-provider"] == "openai"
    assert "authorization" not in headers and "x-tenant-id" not in headers
    assert opener.requests[0][0].full_url == "https://bridge.invalid/mcp"
    assert opener.requests[0][0].get_method() == "POST"
    assert PROVIDER not in opener.requests[0][0].data.decode()


@pytest.mark.parametrize(
    "method,name,args",
    [
        ("initialize", "", {}),
        ("tools/list", "", {}),
        ("resources/read", "", {}),
        ("tools/call", "adaptorch_get_run", {"run_id": RUN_ID}),
        ("tools/call", "adaptorch_cancel_run", {"run_id": RUN_ID}),
        ("tools/call", "adaptorch_usage", {}),
        ("tools/call", "adaptorch_run", {"resume_run_id": RUN_ID}),
    ],
)
def test_non_submit_never_gets_provider_headers(method, name, args):
    opener = Opener()
    transport = HTTPTransport(config(), opener=opener)
    message = rpc(method, name=name, arguments=args)
    transport.request(message)
    assert not any(key.startswith("x-provider") for key in headers_of(opener))
    with pytest.raises(TransportFailure) as exc:
        transport.request(message, submit=True)
    assert exc.value.reason == "provider_boundary"
    assert len(opener.requests) == 1


@pytest.mark.parametrize("received", ["17", 17.0, True, None, 18])
def test_json_rpc_response_id_is_value_and_type_bound(received):
    opener = Opener(Response({"jsonrpc": "2.0", "id": received, "result": {}}))
    with pytest.raises(TransportFailure, match="protocol"):
        HTTPTransport(config(), opener=opener).request(rpc())


@pytest.mark.parametrize(
    "body",
    [
        {"jsonrpc": "2.0", "id": 17, "result": {}, "error": {}},
        {"jsonrpc": "2.0", "id": 17},
        {"id": 17, "result": {}},
        b'{"jsonrpc":"2.0","id":17,"id":17,"result":{}}',
        b'{"jsonrpc":"2.0","id":17,"result":{"x":NaN}}',
        b"\xff",
    ],
)
def test_transport_rejects_malformed_response_envelopes(body):
    with pytest.raises(TransportFailure, match="protocol"):
        HTTPTransport(config(), opener=Opener(Response(body))).request(rpc())


@pytest.mark.parametrize(
    "extra",
    [
        {"Content-Type": "text/event-stream"},
        {"Content-Type": "text/html"},
        {"Content-Type": "application/json", "Content-Encoding": "gzip"},
        {"Content-Type": "application/json", "Content-Length": "-1"},
        {"Content-Type": "application/json", "Content-Length": str(MAX_RESPONSE_BYTES + 1)},
    ],
)
def test_transport_rejects_unexpected_media_or_size(extra):
    with pytest.raises(TransportFailure):
        HTTPTransport(config(), opener=Opener(Response({}, headers=extra))).request(rpc())


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirects_cannot_replay_credentialled_post(status):
    request = Request("https://bridge.invalid/mcp", data=b"{}", headers={"X-API-Key": TENANT})
    with pytest.raises(TransportFailure, match="redirect_blocked"):
        _NoRedirect().redirect_request(request, None, status, "secret", {}, "https://other.invalid")
    opener = Opener(
        exception=HTTPError(
            request.full_url, status, "secret", {"Location": "https://other.invalid"}, None
        )
    )
    with pytest.raises(TransportFailure) as exc:
        HTTPTransport(config(), opener=opener).request(rpc(), submit=True)
    assert exc.value.reason == "redirect_blocked"
    assert len(opener.requests) == 1


def test_default_opener_disables_environment_proxies(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    transport = HTTPTransport(config())
    opener = getattr(transport, "_opener", None)
    if opener is not None:
        assert not any(
            isinstance(handler, ProxyHandler) and handler.proxies for handler in opener.handlers
        )


def test_timeout_is_never_retried_and_does_not_echo_secret():
    opener = Opener(exception=TimeoutError(TENANT + PROVIDER))
    with pytest.raises(TransportFailure) as exc:
        HTTPTransport(config(), opener=opener).request(rpc(), submit=True)
    assert len(opener.requests) == 1
    assert TENANT not in str(exc.value) and PROVIDER not in str(exc.value)
    assert exc.value.sent is True


def test_request_size_failure_does_not_send_or_echo_input():
    opener = Opener()
    with pytest.raises(TransportFailure) as exc:
        HTTPTransport(config(), opener=opener).request(
            rpc(arguments={"prompt": "x" * (1024 * 1024)}), submit=True
        )
    assert exc.value.sent is False
    assert opener.requests == []


def test_transport_response_is_bounded_without_content_length():
    opener = Opener(Response(b" " * (MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(TransportFailure, match="response_too_large"):
        HTTPTransport(config(), opener=opener).request(rpc())


def synthetic_descriptors():
    return [
        {
            "name": name,
            "description": "Synthetic hosted fixture " + TENANT,
            "inputSchema": input_schema(name),
            "annotations": {
                "title": name,
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        }
        for name in TOOL_NAMES
    ]


def test_tool_inventory_is_exact_and_annotations_are_local():
    raw = synthetic_descriptors()
    for name in ("adaptorch_get_traces", "adaptorch_route_topology", "execute_shell"):
        raw.append({"name": name, "description": "should never be advertised"})
    result = tool_descriptors(raw)
    assert [value["name"] for value in result] == list(TOOL_NAMES)
    assert TENANT not in json.dumps(result)
    cancel = next(value for value in result if value["name"] == "adaptorch_cancel_run")
    assert cancel["annotations"]["destructiveHint"] is True
    assert cancel["annotations"]["readOnlyHint"] is False


def test_unsupported_or_unknown_tool_fields_cannot_be_advertised():
    raw = synthetic_descriptors()
    raw[0]["inputSchema"]["properties"].update(
        {
            key: {"type": "string"}
            for key in [
                "trace",
                "verification_commands",
                "idempotency_key",
                "resume_run_id",
                "tenant_id",
                "provider_api_key",
            ]
        }
    )
    result = tool_descriptors(raw)
    assert not set(result[0]["inputSchema"]["properties"]) & {
        "trace",
        "verification_commands",
        "idempotency_key",
        "resume_run_id",
        "tenant_id",
        "provider_api_key",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "missing",
        "open_schema",
        "bad_annotations",
        "missing_run_id",
        "unknown_required",
        "overdeep_schema",
    ],
)
def test_unusable_upstream_tool_contract_fails_closed(mutation):
    raw = synthetic_descriptors()
    if mutation == "duplicate":
        raw.append(deepcopy(raw[0]))
    elif mutation == "missing":
        raw.pop()
    elif mutation == "open_schema":
        raw[0]["inputSchema"]["additionalProperties"] = True
    elif mutation == "bad_annotations":
        raw[0]["annotations"]["readOnlyHint"] = "true"
    elif mutation == "missing_run_id":
        raw[1]["inputSchema"]["properties"] = {}
        raw[1]["inputSchema"]["required"] = []
    elif mutation == "unknown_required":
        raw[0]["inputSchema"]["properties"]["tenant_id"] = {"type": "string"}
        raw[0]["inputSchema"]["required"] = ["tenant_id"]
    else:
        schema = {"type": "string"}
        for _ in range(12):
            schema = {"type": "array", "items": schema}
        raw[0]["inputSchema"]["properties"]["extra"] = schema
    with pytest.raises(ParentContractError):
        tool_descriptors(raw)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"prompt": ""},
        {"prompt": 1},
        {"prompt": "x", "wait": 1},
        {"prompt": "x", "timeout_seconds": 0},
        {"prompt": "x", "timeout_seconds": -1},
        {"prompt": "x", "timeout_seconds": True},
        {"prompt": "x", "timeout_seconds": float("nan")},
        {"prompt": "x", "timeout_seconds": float("inf")},
        {"prompt": "x", "poll_interval_seconds": -1},
        {"prompt": "x", "trace": False},
        {"prompt": "x", "verification_commands": []},
        {"prompt": "x", "resume_run_id": RUN_ID},
        {"prompt": "x", "idempotency_key": "a-key"},
        {"prompt": "x", "tenant_id": "victim"},
        {"prompt": "x", "payload": {"metadata": {"mcp": {"verification_commands": []}}}},
        {"prompt": "x", "payload": {"items": [{"trace": False}]}},
        {"payload": []},
        {"payload": "x"},
        {"prompt": "x", "ensemble_members": [None]},
        {"prompt": "x", "budget_policy": {"nested": {"x": 1}}},
    ],
)
def test_invalid_or_forbidden_run_arguments_fail_locally(arguments):
    assert validate_arguments("adaptorch_run", arguments, input_schema("adaptorch_run")) is False


def test_extreme_wait_integer_is_rejected_without_validator_exception():
    assert (
        validate_arguments(
            "adaptorch_run",
            {"prompt": "x", "timeout_seconds": 10**400},
            input_schema("adaptorch_run"),
        )
        is False
    )


@pytest.mark.parametrize(
    "run_id", ["", "../secret", "https://other.invalid", "run\nheader", "x" * 257, True, 7]
)
def test_run_subject_is_not_a_path_url_or_nonstring(run_id):
    assert (
        validate_arguments(
            "adaptorch_get_run", {"run_id": run_id}, input_schema("adaptorch_get_run")
        )
        is False
    )


@pytest.mark.parametrize("limit", [0, 101, True, 1.5, "20"])
def test_run_list_limit_is_a_bounded_integer(limit):
    assert (
        validate_arguments(
            "adaptorch_list_runs", {"limit": limit}, input_schema("adaptorch_list_runs")
        )
        is False
    )


def test_abusive_content_length_is_classified_without_raw_exception():
    opener = Opener(
        Response({}, headers={"Content-Type": "application/json", "Content-Length": "9" * 5000})
    )
    with pytest.raises(TransportFailure):
        HTTPTransport(config(), opener=opener).request(rpc())


def test_body_read_deadline_stops_without_replay():
    times = iter([0.0, 1.0, 6.0])
    opener = Opener()
    with pytest.raises(TransportFailure, match="deadline"):
        HTTPTransport(config(), opener=opener, clock=lambda: next(times)).request(
            rpc(), submit=True
        )
    assert len(opener.requests) == 1
    assert opener.response.reads == 1


def catalog():
    return {
        "schemaVersion": 1,
        "catalogVersion": "synthetic",
        "billingCycle": "monthly",
        "currency": "USD",
        "sourceOfTruth": [],
        "notes": [],
        "plans": [],
    }


def tool_content(payload, *, error=False, structured=None):
    result = {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": error}
    if structured is not None:
        result["structuredContent"] = structured
    return result


class HostedFixture:
    def __init__(self):
        self.calls = []
        self.tool_payload = {"run_id": RUN_ID, "status": "completed"}
        self.tool_error = False
        self.tool_structured = None
        self.tool_result = None
        self.tool_rpc_error = None
        self.tool_failure = None
        self.prompt_names = list(PROMPT_NAMES)
        self.prompt_messages = [
            {"role": "user", "content": {"type": "text", "text": "synthetic prompt"}}
        ]
        self.resource_uri = RESOURCE_URIS[1]
        self.resource_payload = catalog()
        self.response_id = None

    def request(self, message, *, submit=False):
        self.calls.append((deepcopy(message), submit))
        method = message["method"]
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": TENANT, "version": PROVIDER},
                "capabilities": {
                    "completions": {},
                    "logging": {},
                    "resources": {"subscribe": True, "listChanged": True},
                    "secret": PROVIDER,
                },
            }
        elif method == "tools/list":
            result = {"tools": synthetic_descriptors()}
        elif method == "tools/call":
            if self.tool_failure:
                raise self.tool_failure
            if self.tool_rpc_error:
                return {"jsonrpc": "2.0", "id": message["id"], "error": self.tool_rpc_error}
            result = (
                self.tool_result
                if self.tool_result is not None
                else tool_content(
                    self.tool_payload, error=self.tool_error, structured=self.tool_structured
                )
            )
        elif method == "resources/read":
            result = {
                "contents": [
                    {
                        "uri": self.resource_uri,
                        "mimeType": "application/json",
                        "text": json.dumps(self.resource_payload),
                    }
                ]
            }
        elif method == "prompts/list":
            result = {
                "prompts": [{"name": name, "description": PROVIDER} for name in self.prompt_names]
            }
        elif method == "prompts/get":
            result = {"description": PROVIDER, "messages": self.prompt_messages}
        else:
            raise AssertionError("Unexpected upstream operation: " + method)
        return {
            "jsonrpc": "2.0",
            "id": message["id"] if self.response_id is None else self.response_id,
            "result": result,
        }


def initialized_bridge():
    fixture = HostedFixture()
    bridge = Bridge(config(), transport=fixture)
    response = bridge.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"logging": {}},
                "clientInfo": {"name": "test-client", "version": "1"},
            },
        }
    )
    assert "result" in response
    return bridge, fixture


def decoded_tool(response):
    return json.loads(response["result"]["content"][0]["text"])


def test_upstream_initialize_names_and_capabilities_do_not_leak():
    bridge, fixture = initialized_bridge()
    response = bridge.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": RESOURCE_URIS[0]}}
    )
    payload = json.loads(response["result"]["contents"][0]["text"])
    assert payload["capabilities"] == {
        "tools": {"listChanged": False},
        "resources": {"subscribe": False, "listChanged": False},
        "prompts": {"listChanged": False},
    }
    assert TENANT not in json.dumps(response) and PROVIDER not in json.dumps(response)
    assert len(fixture.calls) == 2


@pytest.mark.parametrize(
    "method,params",
    [
        ("completion/complete", {}),
        ("resources/subscribe", {"uri": RESOURCE_URIS[0]}),
        ("resources/unsubscribe", {"uri": RESOURCE_URIS[0]}),
        ("logging/setLevel", {"level": "debug"}),
        ("tools/call", {"name": "adaptorch_get_traces", "arguments": {"run_id": RUN_ID}}),
        ("tools/call", {"name": "adaptorch_route_topology", "arguments": {}}),
        ("resources/read", {"uri": "file:///tmp/secret"}),
        ("resources/read", {"uri": "https://other.invalid/secret"}),
        ("prompts/get", {"name": "execute_shell", "arguments": {}}),
    ],
)
def test_disallowed_methods_never_reach_upstream(method, params):
    bridge, fixture = initialized_bridge()
    response = bridge.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": method, "params": params}
    )
    assert "error" in response
    assert len(fixture.calls) == 2


@pytest.mark.parametrize(
    "method",
    [
        "notifications/cancelled",
        "notifications/initialized",
        "notifications/progress",
        "tools/call",
        "shutdown",
    ],
)
def test_notifications_never_send_write_or_response(method):
    bridge, fixture = initialized_bridge()
    assert (
        bridge.handle_message(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": {"name": "adaptorch_run", "arguments": {"prompt": "x"}, "requestId": 12},
            }
        )
        is None
    )
    assert len(fixture.calls) == 2


def test_shutdown_is_local_and_prevents_more_hosted_calls():
    bridge, fixture = initialized_bridge()
    assert (
        bridge.handle_message({"jsonrpc": "2.0", "id": 2, "method": "shutdown"})["result"] is None
    )
    assert "error" in bridge.handle_message(rpc())
    assert bridge.handle_message({"jsonrpc": "2.0", "method": "exit"}) is None
    assert bridge.exited
    assert len(fixture.calls) == 2


def test_submitted_timeout_is_uncertain_once_and_never_cancels():
    bridge, fixture = initialized_bridge()
    fixture.tool_failure = TransportFailure("deadline")
    response = bridge.handle_message(rpc())
    payload = decoded_tool(response)
    assert response["result"]["isError"] is True
    assert payload["request_outcome"] == "unknown"
    assert payload["new_run_safe"] is False and payload["automatic_retry"] is False
    assert len(fixture.calls) == 3
    assert fixture.calls[-1][1] is True
    assert [call[0]["params"].get("name") for call in fixture.calls].count(
        "adaptorch_cancel_run"
    ) == 0


@pytest.mark.parametrize(
    "name", ["adaptorch_get_run", "adaptorch_cancel_run", "adaptorch_get_artifacts"]
)
@pytest.mark.parametrize("is_error", [False, True])
def test_success_and_error_response_run_subject_cannot_change(name, is_error):
    bridge, fixture = initialized_bridge()
    fixture.tool_payload = {
        "run_id": "run-victim-B",
        "status": "completed",
        "artifacts": {},
        "error": "CONTROL_PLANE_REJECTED",
        "status_code": 401,
        "message": PROVIDER,
    }
    fixture.tool_error = is_error
    response = bridge.handle_message(rpc(name=name, arguments={"run_id": RUN_ID}))
    assert response["result"]["isError"] is True
    assert "run-victim-B" not in json.dumps(response)
    assert PROVIDER not in json.dumps(response)
    assert decoded_tool(response)["run_id"] == RUN_ID


@pytest.mark.parametrize(
    "ref",
    [
        "/tmp/secret",
        "//other.invalid/secret",
        "file:///tmp/secret",
        "javascript:alert(1)",
        "https://user:secret@other.invalid/result",
        "https://other.invalid/a/../secret",
        "https://other.invalid/a/%2e%2e/secret",
        "https://other.invalid/result#secret",
        "https://[broken",
    ],
)
def test_unsafe_artifact_references_are_rejected(ref):
    bridge, fixture = initialized_bridge()
    fixture.tool_payload = {"run_id": RUN_ID, "artifacts": {"result": ref}}
    response = bridge.handle_message(
        rpc(name="adaptorch_get_artifacts", arguments={"run_id": RUN_ID})
    )
    assert "error" in response or response["result"]["isError"] is True
    assert ref not in json.dumps(response)


def test_unknown_fields_and_untrusted_structured_content_are_dropped():
    bridge, fixture = initialized_bridge()
    fixture.tool_payload = {
        "run_id": RUN_ID,
        "status": "completed",
        "provider_key": PROVIDER,
        "trace": "sensitive trace",
        "metadata": {"secret": "hidden"},
    }
    fixture.tool_structured = {"run_id": "run-victim-B", "secret": "hidden"}
    response = bridge.handle_message(rpc(name="adaptorch_get_run", arguments={"run_id": RUN_ID}))
    assert response["result"]["isError"] is False
    assert response["result"]["structuredContent"] == decoded_tool(response)
    assert not any(
        secret in json.dumps(response)
        for secret in [PROVIDER, "hidden", "sensitive trace", "run-victim-B"]
    )


@pytest.mark.parametrize(
    "error_code,status",
    [
        ("CONTROL_PLANE_REJECTED", 401),
        ("CONTROL_PLANE_REJECTED", 403),
        ("CONTROL_PLANE_UNAVAILABLE", 503),
        ("QUOTA_EXCEEDED", 429),
    ],
)
def test_raw_error_text_and_credentials_never_leave_bridge(error_code, status):
    bridge, fixture = initialized_bridge()
    fixture.tool_error = True
    fixture.tool_payload = {
        "error": error_code,
        "status_code": status,
        "message": TENANT + PROVIDER,
        "message_ko": PROVIDER,
        "usage": {"used": 1, "limit": 1},
        "operator_context": "private",
    }
    response = bridge.handle_message(rpc())
    encoded = json.dumps(response)
    assert TENANT not in encoded and PROVIDER not in encoded and "private" not in encoded
    assert decoded_tool(response)["status_code"] == status


def test_tenant_cannot_change_midprocess():
    bridge, fixture = initialized_bridge()
    fixture.tool_payload = {"tenant_id": "tenant-A", "used": 1, "limit": 100}
    assert (
        bridge.handle_message(rpc(name="adaptorch_usage", arguments={}))["result"]["isError"]
        is False
    )
    fixture.tool_payload["tenant_id"] = "tenant-B"
    response = bridge.handle_message(rpc(name="adaptorch_usage", arguments={}))
    assert response["result"]["isError"] is True
    assert "tenant-B" not in json.dumps(response)


def test_metrics_and_resource_inventory_are_client_local():
    bridge, fixture = initialized_bridge()
    for method in ["resources/list", "resources/templates/list", "tools/list"]:
        response = bridge.handle_message({"jsonrpc": "2.0", "id": 10, "method": method})
        assert "result" in response
    response = bridge.handle_message(rpc(name="adaptorch_server_metrics", arguments={}))
    assert decoded_tool(response)["tool_calls"] == 1
    assert len(fixture.calls) == 2


def test_resource_uri_must_match_requested_subject():
    bridge, fixture = initialized_bridge()
    fixture.resource_uri = "https://other.invalid/secret"
    response = bridge.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": RESOURCE_URIS[1]}}
    )
    assert "error" in response
    assert fixture.resource_uri not in json.dumps(response)


def test_prompt_inventory_is_filtered_and_its_text_is_locally_owned():
    bridge, fixture = initialized_bridge()
    fixture.prompt_names += ["execute_shell"]
    response = bridge.handle_message({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"})
    assert [prompt["name"] for prompt in response["result"]["prompts"]] == list(PROMPT_NAMES)
    assert PROVIDER not in json.dumps(response)


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "system", "content": {"type": "text", "text": "x"}}],
        [{"role": "user", "content": {"type": "image", "data": "x"}}],
        [
            {
                "role": "user",
                "content": {"type": "resource", "resource": {"uri": "file:///tmp/secret"}},
            }
        ],
        [],
        [{"role": "user", "content": {"type": "text", "text": "x" * 100001}}],
    ],
)
def test_unsafe_prompt_result_shapes_are_rejected(messages):
    bridge, fixture = initialized_bridge()
    fixture.prompt_messages = messages
    response = bridge.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "prompts/get",
            "params": {"name": PROMPT_NAMES[0], "arguments": {"prompt": "x"}},
        }
    )
    assert "error" in response


def test_secret_text_in_allowed_output_fields_is_redacted():
    bridge, fixture = initialized_bridge()
    fixture.tool_payload["model"] = TENANT + " " + PROVIDER
    response = bridge.handle_message(rpc(name="adaptorch_get_run", arguments={"run_id": RUN_ID}))
    assert response["result"]["isError"] is False
    assert TENANT not in json.dumps(response) and PROVIDER not in json.dumps(response)


def test_projector_failure_after_submit_preserves_uncertain_write_outcome():
    bridge, fixture = initialized_bridge()
    fixture.tool_payload = {
        "run_id": RUN_ID,
        "status": "completed",
        "artifact_urls": {"result": "https://[broken"},
    }
    response = bridge.handle_message(rpc())
    assert response["result"]["isError"] is True
    payload = decoded_tool(response)
    assert payload["request_outcome"] == "unknown"
    assert payload["new_run_safe"] is False and payload["automatic_retry"] is False
    assert len(fixture.calls) == 3


def test_nested_recovery_subject_is_bound_to_the_requested_run():
    bridge, fixture = initialized_bridge()
    fixture.tool_payload = {
        "run_id": RUN_ID,
        "status": "failed",
        "recovery": {
            "schema_version": 1,
            "run_id": "run-victim-B",
            "request_outcome": "unknown",
            "reason": "deadline",
            "new_run_safe": False,
            "next_action": "resume_existing_run",
        },
    }
    response = bridge.handle_message(rpc(name="adaptorch_get_run", arguments={"run_id": RUN_ID}))
    assert "run-victim-B" not in json.dumps(response)


def test_prompt_get_requires_validated_advertised_name():
    bridge, fixture = initialized_bridge()
    fixture.prompt_names = ["execute_shell"]
    response = bridge.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "prompts/get",
            "params": {"name": PROMPT_NAMES[0], "arguments": {"prompt": "x"}},
        }
    )
    assert "error" in response
    assert not any(call[0]["method"] == "prompts/get" for call in fixture.calls)


@pytest.mark.parametrize("action", ["resume_existing_run", "reuse_same_request_and_key"])
def test_recovery_cannot_advertise_unsupported_replay_or_resume(action):
    bridge, fixture = initialized_bridge()
    fixture.tool_payload = {
        "run_id": RUN_ID,
        "status": "failed",
        "recovery": {
            "schema_version": 1,
            "run_id": RUN_ID,
            "request_outcome": "unknown",
            "reason": "deadline",
            "new_run_safe": True,
            "replay_safe": True,
            "next_action": action,
        },
    }
    response = bridge.handle_message(rpc(name="adaptorch_get_run", arguments={"run_id": RUN_ID}))
    payload = decoded_tool(response)
    recovery = payload.get("recovery") or {}
    assert recovery.get("new_run_safe") is not True
    assert recovery.get("replay_safe") is not True
    assert recovery.get("next_action") not in {"resume_existing_run", "reuse_same_request_and_key"}


# Capture the originals while importing, before the autouse network guard runs.
# The two integration tests below restore only an exact 127.0.0.1 connection.
_REAL_SOCKET_CONNECT = socket.socket.connect


@pytest.fixture
def only_loopback_connections(monkeypatch):
    def loopback_connect(sock, address):
        if not isinstance(address, tuple) or address[0] != "127.0.0.1":
            raise AssertionError("Non-loopback connection forbidden in review")
        return _REAL_SOCKET_CONNECT(sock, address)

    def create_loopback(
        address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **_kwargs
    ):
        if address[0] != "127.0.0.1":
            raise AssertionError("DNS and non-loopback connections forbidden in review")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(timeout)
        if source_address:
            if source_address[0] not in {"", "127.0.0.1"}:
                raise AssertionError("Non-loopback source forbidden in review")
            sock.bind(source_address)
        try:
            sock.connect(address)
        except BaseException:
            sock.close()
            raise
        return sock

    monkeypatch.setattr(socket.socket, "connect", loopback_connect)
    monkeypatch.setattr(socket, "create_connection", create_loopback)
    # DNS, connect_ex and every non-loopback connect remain denied.


@pytest.mark.parametrize("drip_target", ["headers", "body"])
def test_production_loopback_slow_drip_is_cut_off_without_proxy_or_replay(
    only_loopback_connections, monkeypatch, drip_target
):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    port = listener.getsockname()[1]
    stop = threading.Event()
    accepted = []
    errors = []

    def serve():
        try:
            peer, _address = listener.accept()
            accepted.append(True)
            with peer:
                peer.settimeout(1)
                request = b""
                while b"\r\n\r\n" not in request:
                    request += peer.recv(8192)
                body = json.dumps(
                    {"jsonrpc": "2.0", "id": 17, "result": {"slow": "x" * 100}}
                ).encode()
                headers = (
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\n\r\n"
                )
                if drip_target == "body":
                    peer.sendall(headers)
                    wire = body
                else:
                    wire = headers + body
                for byte in wire:
                    if stop.wait(0.025):
                        break
                    peer.sendall(bytes([byte]))
        except OSError:
            pass  # A deadline abort intentionally closes the connection mid-response.
        except BaseException as exc:
            errors.append(exc)
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    cfg = BridgeConfig(
        ClientConfig(f"http://127.0.0.1:{port}", TENANT, 0.2), allow_loopback_http=True
    )
    started = time.monotonic()
    try:
        with pytest.raises(TransportFailure) as exc:
            HTTPTransport(cfg).request(rpc(), submit=True)
        elapsed = time.monotonic() - started
        assert exc.value.sent is True
        assert elapsed < 1.0, f"Dripping {drip_target} exceeded bounded walltime: {elapsed:.3f}s"
        assert accepted == [True]
        assert not errors
    finally:
        stop.set()
        listener.close()
        thread.join(2)


@pytest.mark.parametrize(
    "header",
    [
        b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
        b"Content-Length: 2\r\ncontent-length: 2\r\n\r\n{}",
        b"Content-Length: -1\r\n\r\n{}",
        b"Content-Length: 1.5\r\n\r\n{}",
        b"Content-Length: 1048577\r\n\r\n{}",
        b"Content-Length: 2\n\n{}",
        b"Content-Length: 2\r\nX-Provider-Key: secret\r\n\r\n{}",
        b"Content-Type: text/html\r\nContent-Length: 2\r\n\r\n{}",
        b"Content-Length: 10\r\n\r\n{}",
        b"Content-Type: application/json\r\n\r\n{}",
        b"Content-Length: " + b"9" * 9000 + b"\r\n\r\n{}",
    ],
)
def test_ambiguous_or_malformed_stdio_frames_fail_closed(header):
    with pytest.raises(FramingError):
        read_message(io.BytesIO(header), "content-length")


@pytest.mark.parametrize("framing", ["line", "content-length"])
def test_notification_stdio_output_stays_empty(framing):
    bridge, fixture = initialized_bridge()
    body = json.dumps(
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 123}}
    ).encode()
    wire = (
        body + b"\n"
        if framing == "line"
        else f"Content-Length: {len(body)}\r\n\r\n".encode() + body
    )
    output = io.BytesIO()
    assert serve(bridge, io.BytesIO(wire), output, framing) == 0
    assert output.getvalue() == b""
    assert len(fixture.calls) == 2


def test_oversized_frame_stops_before_any_trailing_submission():
    bridge, fixture = initialized_bridge()
    submission = json.dumps(rpc()).encode()
    wire = b"Content-Length: 1048577\r\n\r\n" + submission
    output = io.BytesIO()
    assert serve(bridge, io.BytesIO(wire), output, "content-length") == 2
    assert len(fixture.calls) == 2
    assert b"Invalid or oversized frame" in output.getvalue()


def test_duplicate_json_keys_cannot_smuggle_a_second_tool_name():
    bridge, fixture = initialized_bridge()
    wire = (
        b'{"jsonrpc":"2.0","id":4,"method":"tools/call","params":'
        b'{"name":"adaptorch_usage","name":"adaptorch_run","arguments":{"prompt":"x"}}}\n'
    )
    output = io.BytesIO()
    assert serve(bridge, io.BytesIO(wire), output) == 0
    assert json.loads(output.getvalue())["error"]["code"] == -32700
    assert len(fixture.calls) == 2


def test_standalone_source_never_imports_private_engine():
    root = Path(__file__).resolve().parents[1] / "src" / "adaptorch_mcp"
    violations = []
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            violations.extend(
                (path.name, name)
                for name in names
                if name and (name == "adaptorch" or name.startswith("adaptorch."))
            )
    assert violations == []


def test_each_list_item_binds_its_own_nested_run_subject():
    bridge, fixture = initialized_bridge()
    fixture.tool_payload = {
        "items": [
            {
                "run_id": RUN_ID,
                "status": "failed",
                "recovery": {"schema_version": 1, "run_id": "run-victim-B", "reason": "deadline"},
            }
        ],
        "total": 1,
    }
    response = bridge.handle_message(rpc(name="adaptorch_list_runs", arguments={}))
    assert "run-victim-B" not in json.dumps(response)


@pytest.mark.parametrize("is_error", [True, False])
def test_submitted_run_id_is_retained_when_error_or_projection_fails(is_error):
    bridge, fixture = initialized_bridge()
    fixture.tool_error = is_error
    fixture.tool_payload = {
        "run_id": RUN_ID,
        "status": "running",
        "error": "CONTROL_PLANE_UNAVAILABLE",
        "status_code": 503,
        "artifact_urls": {"result": "https://[broken"},
    }
    response = bridge.handle_message(rpc())
    assert response["result"]["isError"] is True
    payload = decoded_tool(response)
    assert payload.get("run_id") == RUN_ID
    assert payload["request_outcome"] == "unknown"
    assert payload["new_run_safe"] is False


def test_requested_subject_cannot_leak_a_configured_secret_in_fixed_error():
    bridge, fixture = initialized_bridge()
    fixture.tool_failure = TransportFailure("network")
    response = bridge.handle_message(rpc(name="adaptorch_get_run", arguments={"run_id": TENANT}))
    assert TENANT not in json.dumps(response)


def test_repeated_native_success_error_deadline_reclaims_threads_and_sockets(
    only_loopback_connections,
):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    port = listener.getsockname()[1]
    modes = ["success", "error", "deadline"] * 4
    finished = [threading.Event() for _ in modes]
    stop = threading.Event()
    accepted = []
    errors = []

    def serve_repeated():
        try:
            for index, mode in enumerate(modes):
                peer, _address = listener.accept()
                accepted.append(mode)
                with peer:
                    peer.settimeout(1)
                    request = b""
                    while b"\r\n\r\n" not in request:
                        request += peer.recv(8192)
                    if mode == "deadline":
                        stop.wait(0.16)
                    else:
                        body = b'{"jsonrpc":"2.0","id":17,"result":{}}'
                        status = b"200 OK" if mode == "success" else b"503 Service Unavailable"
                        peer.sendall(
                            b"HTTP/1.1 "
                            + status
                            + b"\r\nContent-Type: application/json\r\nContent-Length: "
                            + str(len(body)).encode()
                            + b"\r\n\r\n"
                            + body
                        )
                finished[index].set()
        except OSError:
            if not stop.is_set():
                errors.append("loopback server unexpectedly failed")
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=serve_repeated, daemon=True)
    thread.start()
    baseline_threads = {id(value) for value in threading.enumerate()}
    baseline_fds = len(list(Path("/proc/self/fd").iterdir()))
    cfg = BridgeConfig(
        ClientConfig(f"http://127.0.0.1:{port}", TENANT, 0.1), allow_loopback_http=True
    )
    transport = HTTPTransport(cfg)
    try:
        for index, mode in enumerate(modes):
            if mode == "success":
                assert transport.request(rpc(), submit=True)["result"] == {}
            else:
                with pytest.raises(TransportFailure) as exc:
                    transport.request(rpc(), submit=True)
                assert exc.value.sent is True
                if mode == "error":
                    assert exc.value.status == 503
            assert finished[index].wait(1), "loopback fixture did not finish its request"
            assert len(accepted) == index + 1, "request was unexpectedly replayed"
            assert {id(value) for value in threading.enumerate()}.issubset(baseline_threads)
            assert len(list(Path("/proc/self/fd").iterdir())) <= baseline_fds
            assert not errors
    finally:
        stop.set()
        listener.close()
        thread.join(2)
    assert not thread.is_alive()


class OwnedTransportHarness:
    """Deterministic native-path connection/timer race fixture; no real sockets."""

    def __init__(self, monkeypatch, *, stage=None, stuck=False, will_close=False):
        import adaptorch_mcp.transport as module

        self.now = 0.0
        self.stage = stage
        self.stuck = stuck
        self.will_close = will_close
        self.responses = []
        self.connections = []
        self.timers = []
        self.post_attempts = []
        self.open_sockets = 0
        harness = self

        class OwnedSocket:
            def __init__(self):
                self.closed = False
                self.timeout = None
                self.shutdowns = []
                harness.open_sockets += 1

            def settimeout(self, value):
                self.timeout = value

            def shutdown(self, how):
                self.shutdowns.append(how)
                if self.closed:
                    raise OSError(TENANT + PROVIDER)

            def close(self):
                if not self.closed:
                    harness.open_sockets -= 1
                    self.closed = True

        class ControlledTimer:
            def __init__(self, interval, callback):
                self.interval = interval
                self.callback = callback
                self.daemon = False
                self.started = False
                self.cancelled = False
                self.join_timeouts = []
                self.fired = False
                harness.timers.append(self)

            def start(self):
                self.started = True
                if harness.stage == "before_request":
                    self.fire()

            def fire(self):
                if not self.fired:
                    self.fired = True
                    harness.now = 5.01
                    self.callback()

            def cancel(self):
                self.cancelled = True
                if harness.stage == "cleanup":
                    self.fire()

            def join(self, timeout=None):
                self.join_timeouts.append(timeout)

            def is_alive(self):
                return harness.stuck

        class ControlledResponse(Response):
            def __init__(self, owned_socket):
                super().__init__({"jsonrpc": "2.0", "id": 17, "result": {}})
                self.owned_socket = owned_socket
                self.will_close = harness.will_close
                self.closed = False
                harness.responses.append(self)
                if self.will_close:
                    self.headers["Connection"] = "close"
                if harness.stage == "http_error":
                    self.status = 503
                elif harness.stage == "redirect":
                    self.status = 307
                    self.headers["Location"] = "https://other.invalid/collect"

            def close(self):
                self.closed = True
                self.owned_socket.close()

            def read1(self, size):
                if harness.stage == "response_body":
                    harness.timers[-1].fire()
                    raise OSError(TENANT + PROVIDER)
                return self.read(size)

        class OwnedConnection:
            def __init__(self, host, *, port, timeout):
                self.host = host
                self.port = port
                self.timeout = timeout
                self.sock = None
                self.closed = False
                self.connects = 0
                self.responses = 0
                harness.connections.append(self)

            def connect(self):
                self.connects += 1
                self.sock = OwnedSocket()
                if harness.stage == "after_connect_budget":
                    harness.now = 5.01

            def request(self, method, path, *, body, headers):
                harness.post_attempts.append((method, path, body, headers))
                if harness.stage == "request_write":
                    harness.timers[-1].fire()
                    raise OSError(TENANT + PROVIDER)
                if self.sock.closed:
                    raise OSError(TENANT + PROVIDER)

            def getresponse(self):
                self.responses += 1
                if harness.stage == "response_headers":
                    harness.timers[-1].fire()
                    raise OSError(TENANT + PROVIDER)
                response = ControlledResponse(self.sock)
                if harness.will_close:
                    self.sock = None  # Match HTTPConnection detachment on will_close.
                return response

            def close(self):
                self.closed = True
                if self.sock is not None:
                    self.sock.close()

        monkeypatch.setattr(module, "HTTPSConnection", OwnedConnection)
        monkeypatch.setattr(module, "HTTPConnection", OwnedConnection)
        monkeypatch.setattr(module.threading, "Timer", ControlledTimer)

    def clock(self):
        return self.now


def test_native_post_connect_budget_exhaustion_is_definitely_not_sent(monkeypatch):
    harness = OwnedTransportHarness(monkeypatch, stage="after_connect_budget")
    with pytest.raises(TransportFailure) as exc:
        HTTPTransport(config(), clock=harness.clock).request(rpc(), submit=True)
    assert exc.value.reason == "deadline"
    assert exc.value.sent is False
    assert harness.post_attempts == []
    assert harness.timers == []
    assert len(harness.connections) == 1
    assert harness.connections[0].closed
    assert harness.open_sockets == 0
    assert TENANT not in str(exc.value) and PROVIDER not in str(exc.value)


@pytest.mark.parametrize(
    "stage", ["before_request", "request_write", "response_headers", "response_body"]
)
def test_native_watchdog_close_race_is_single_attempt_uncertain_and_secret_free(monkeypatch, stage):
    harness = OwnedTransportHarness(monkeypatch, stage=stage)
    with pytest.raises(TransportFailure) as exc:
        HTTPTransport(config(), clock=harness.clock).request(rpc(), submit=True)
    assert exc.value.reason == "deadline"
    assert exc.value.sent is True  # Preserve uncertainty once the send path was entered.
    assert TENANT not in str(exc.value) and PROVIDER not in str(exc.value)
    assert len(harness.connections) == len(harness.timers) == len(harness.post_attempts) == 1
    assert harness.post_attempts[0][0:2] == ("POST", "/mcp")
    sent = json.loads(harness.post_attempts[0][2])
    assert sent["params"]["name"] == "adaptorch_run"
    assert harness.timers[0].fired and harness.timers[0].cancelled
    assert harness.timers[0].join_timeouts == [1.0]
    assert harness.connections[0].closed and harness.open_sockets == 0


def test_native_watchdog_close_racing_cleanup_keeps_complete_response_and_reclaims_socket(
    monkeypatch,
):
    harness = OwnedTransportHarness(monkeypatch, stage="cleanup")
    response = HTTPTransport(config(), clock=harness.clock).request(rpc(), submit=True)
    assert response == {"jsonrpc": "2.0", "id": 17, "result": {}}
    assert len(harness.post_attempts) == len(harness.connections) == len(harness.timers) == 1
    assert harness.timers[0].fired and harness.timers[0].cancelled
    assert harness.timers[0].join_timeouts == [1.0]
    assert harness.connections[0].closed and harness.open_sockets == 0
    assert TENANT not in json.dumps(response) and PROVIDER not in json.dumps(response)


@pytest.mark.parametrize("stage", [None, "request_write", "response_headers", "response_body"])
def test_stuck_watchdog_join_is_bounded_and_disables_future_transport_without_new_timer(
    monkeypatch, stage
):
    harness = OwnedTransportHarness(monkeypatch, stage=stage, stuck=True)
    transport = HTTPTransport(config(), clock=harness.clock)
    if stage is None:
        assert transport.request(rpc(), submit=True)["result"] == {}
    else:
        with pytest.raises(TransportFailure) as first:
            transport.request(rpc(), submit=True)
        assert first.value.sent is True
    assert harness.timers[0].join_timeouts == [1.0]
    assert harness.connections[0].closed and harness.open_sockets == 0
    for _ in range(3):
        with pytest.raises(TransportFailure) as later:
            transport.request(rpc(), submit=True)
        assert later.value.reason == "transport_disabled"
        assert later.value.sent is False
        assert TENANT not in str(later.value) and PROVIDER not in str(later.value)
    assert len(harness.connections) == len(harness.timers) == len(harness.post_attempts) == 1


@pytest.mark.parametrize("secret", [TENANT, PROVIDER])
@pytest.mark.parametrize("is_error", [True, False])
def test_submit_error_observed_secret_run_id_is_never_echoed(secret, is_error):
    bridge, fixture = initialized_bridge()
    fixture.tool_error = is_error
    fixture.tool_payload = {
        "run_id": secret,
        "status": "running",
        "status_code": 503,
        "artifact_urls": {"result": "https://[broken"},
    }
    response = bridge.handle_message(rpc())
    assert response["result"]["isError"] is True
    assert secret not in json.dumps(response)
    assert decoded_tool(response)["request_outcome"] == "unknown"


@pytest.mark.parametrize("will_close", [False, True])
@pytest.mark.parametrize("stage", [None, "http_error", "response_body", "redirect"])
def test_owned_response_is_explicitly_closed_even_when_http_connection_detaches(
    monkeypatch, stage, will_close
):
    harness = OwnedTransportHarness(monkeypatch, stage=stage, will_close=will_close)
    transport = HTTPTransport(config(), clock=harness.clock)
    if stage is None:
        assert transport.request(rpc(), submit=True)["result"] == {}
    else:
        with pytest.raises(TransportFailure) as exc:
            transport.request(rpc(), submit=True)
        assert exc.value.sent is True
        if stage == "redirect":
            assert exc.value.reason == "redirect_blocked" and exc.value.status == 307
        elif stage == "http_error":
            assert exc.value.status == 503
        else:
            assert exc.value.reason == "deadline"
    assert len(harness.responses) == len(harness.post_attempts) == len(harness.connections) == 1
    assert harness.responses[0].closed
    assert harness.responses[0].owned_socket.closed
    assert harness.open_sockets == 0
    assert harness.connections[0].closed
    assert harness.timers[0].cancelled and harness.timers[0].join_timeouts == [1.0]
