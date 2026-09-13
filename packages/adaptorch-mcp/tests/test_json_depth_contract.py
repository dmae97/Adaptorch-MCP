"""SDK and MCP enforce a portable depth bound without counting quoted brackets."""

import json

import pytest
from adaptorch.n8n_connector import N8nConnectorError

from adaptorch_client import AdaptOrchAPIError, JSONMapping, JSONValue
from adaptorch_client.transport import HTTPTransport
from adaptorch_mcp.control_plane_backend import _json_object
from adaptorch_mcp.response_json import decode_response_text


@pytest.mark.parametrize("arrays,allowed", [(63, True), (64, False), (1100, False)])
def test_json_depth_bound_counts_root_and_nested_containers(arrays: int, allowed: bool) -> None:
    value: JSONValue = None
    for _ in range(arrays):
        value = [value]
    payload: JSONMapping = {"x": value}
    text = '{"x":' + "[" * arrays + "null" + "]" * arrays + "}"
    if allowed:
        assert HTTPTransport._decode_mapping(text.encode()) == payload
        assert HTTPTransport._encode_payload(payload) is not None
        assert _json_object(text.encode()) == payload
        assert decode_response_text(text) == payload
    else:
        with pytest.raises(AdaptOrchAPIError):
            HTTPTransport._decode_mapping(text.encode())
        with pytest.raises(AdaptOrchAPIError):
            HTTPTransport._encode_payload(payload)
        with pytest.raises(N8nConnectorError):
            _json_object(text.encode())
        assert decode_response_text(text) is None


@pytest.mark.parametrize("value", ["[" * 2000, '\\"[{}]' * 1000, 'quotes " and slashes \\\\'])
def test_quoted_and_escaped_brackets_do_not_count_as_structure(value: str) -> None:
    payload: JSONMapping = {"x": value}
    text = json.dumps(payload)
    assert HTTPTransport._decode_mapping(text.encode()) == payload
    assert decode_response_text(text) == payload
