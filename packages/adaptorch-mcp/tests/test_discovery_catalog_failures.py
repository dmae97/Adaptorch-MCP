"""Corrupt package resources must refuse discovery, not escape as raw exceptions."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from adaptorch_mcp import thin_remote


@pytest.fixture
def catalogs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    tools = thin_remote.discovery_catalog()
    route = next(t for t in tools if t['name'] == 'adaptorch_route_topology')
    core = [t for t in tools if t['name'] in thin_remote.REMOTE_TOOL_NAMES]
    (tmp_path / 'remote_tool_catalog.json').write_text(json.dumps({'tools': core}))
    (tmp_path / 'route_tool_contract.json').write_text(json.dumps(route))
    monkeypatch.setattr(thin_remote, 'files', lambda _package: tmp_path)
    thin_remote._load_catalog.cache_clear()
    yield tmp_path
    thin_remote._load_catalog.cache_clear()


@pytest.mark.parametrize('resource', ['remote_tool_catalog.json', 'route_tool_contract.json'])
@pytest.mark.parametrize('fault', ['missing', 'json', 'shape', 'tool_name'])
def test_catalog_failure_is_a_bounded_protocol_refusal(
    catalogs: Path, resource: str, fault: str,
) -> None:
    path = catalogs / resource
    if fault == 'missing':
        path.unlink()
    elif fault == 'json':
        path.write_text('{broken')
    elif fault == 'shape':
        path.write_text('[]')
    else:
        value: dict[str, Any] = json.loads(path.read_text())
        if resource == 'remote_tool_catalog.json':
            value['tools'][0]['name'] = 'private_tool'
        else:
            value['name'] = 'private_tool'
        path.write_text(json.dumps(value))
    server = thin_remote.RemoteMCPServer.discovery_only()
    response = server.handle_message({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/list'})
    assert response == {'jsonrpc': '2.0', 'id': 5, 'error': {
        'code': -32603, 'message': 'Discovery catalog unavailable',
    }}
    assert str(catalogs) not in json.dumps(response)
    # Damaged discovery data can never turn the no-token transport into an executor.
    denied = server.handle_message({'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call', 'params': {
        'name': 'adaptorch_route_topology',
        'arguments': {'subtasks': [{'id': 'one', 'description': 'offline'}]},
    }})
    assert denied is not None and denied['error']['code'] == -32001
