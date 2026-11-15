from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from adaptorch_mcp.audit_output import AUDIT_TOOL_NAMES, audit_contract, project_audit_output
from adaptorch_mcp.public_schema import ParentContractError, project_remote_tool
from adaptorch_mcp.response_policy import sanitize_tool_response
from adaptorch_mcp.thin_remote import RemoteMCPServer, discovery_catalog


def status() -> dict[str, Any]:
    return {'schema_version': 'audit.status.v1', 'audit_id': 'audit-1', 'task_id': 'task-1',
            'turn_id': 'turn-1', 'status': 'QUEUED', 'request_sha256': 'a' * 64,
            'snapshot_sha256': 'b' * 64, 'is_current': True, 'validation_state': None,
            'error_code': None, 'created_at': 1.0, 'finished_at': None,
            'events': [{'sequence': 1, 'code': 'audit_requested', 'at': 1.0}],
            'is_correctness_proof': False}


def envelope(body: dict[str, Any]) -> dict[str, Any]:
    return {'jsonrpc': '2.0', 'id': 1, 'result': {
        'content': [{'type': 'text', 'text': json.dumps(body)}], 'isError': False,
    }}


def test_opt_in_schemas_preserve_full_output_contract_without_advertising_offline() -> None:
    assert not set(AUDIT_TOOL_NAMES) & {item['name'] for item in discovery_catalog()}
    for name in AUDIT_TOOL_NAMES:
        contract = audit_contract(name)
        assert project_remote_tool(contract) == contract
        changed = deepcopy(contract)
        changed['outputSchema']['additionalProperties'] = True
        with pytest.raises(ParentContractError):
            project_remote_tool(changed)


def test_output_schema_rejects_authority_unknowns_nonfinite_and_unbounded_events() -> None:
    value = status()
    assert project_audit_output('adaptorch_audit', value) == value
    for update in [
        {'is_correctness_proof': True}, {'execute_patch': 'secret'}, {'created_at': float('nan')},
        {'events': value['events'] * 17}, {'audit_id': '../foreign'}, {'status': 'APPROVED'},
        {'created_at': True}, {'request_sha256': 'invalid'},
    ]:
        assert project_audit_output('adaptorch_get_audit', {**value, **update}) is None


def test_sanitizer_binds_audit_id_and_keeps_structured_output() -> None:
    safe = sanitize_tool_response(envelope(status()), tool_name='adaptorch_get_audit',
                                  expected_audit_id='audit-1')['result']
    assert safe['structuredContent'] == status()
    assert json.loads(safe['content'][0]['text']) == safe['structuredContent']
    assert sanitize_tool_response(envelope(status()), tool_name='adaptorch_get_audit',
                                  expected_audit_id='other')['result']['isError']


def test_artifact_utf8_bytes_and_cursor_consistency() -> None:
    value = {'schema_version': 'audit.artifact-page.v1', 'audit_id': 'audit-1', 'kind': 'request',
             'snapshot_sha256': 'b' * 64, 'artifact_sha256': 'c' * 64,
             'total_bytes': 6, 'offset_bytes': 0, 'returned_bytes': 6,
             'text': '한글', 'has_more': False, 'next_cursor': None}
    assert project_audit_output('adaptorch_get_audit_artifact', value) == value
    assert sanitize_tool_response(envelope(value), tool_name='adaptorch_get_audit_artifact',
                                  expected_audit_id='audit-1', expected_audit_kind='candidates')[
                                      'result']['isError']
    for update in [{'returned_bytes': 2}, {'has_more': True}, {'next_cursor': 'unexpected'},
                   {'offset_bytes': 1}, {'text': 'x' * 16385}]:
        assert project_audit_output('adaptorch_get_audit_artifact', {**value, **update}) is None


def test_remote_forwards_audit_without_provider_credentials_and_filters_bad_args() -> None:
    class Transport:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        def request(self, spec: Any) -> dict[str, Any]:
            self.calls.append(spec)
            return envelope(status())

        def close(self) -> None:
            pass

    transport = Transport()
    server = RemoteMCPServer(transport)
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'adaptorch_get_audit', 'arguments': {'audit_id': 'audit-1'},
    }}
    response = server.handle_message(request)
    assert response is not None and response['result']['structuredContent'] == status()
    assert transport.calls[0].provider_credential is None
    request['params']['arguments']['commands'] = ['forbidden']
    rejected = server.handle_message(request)
    assert rejected is not None and rejected['error']['code'] == -32602
    assert len(transport.calls) == 1
