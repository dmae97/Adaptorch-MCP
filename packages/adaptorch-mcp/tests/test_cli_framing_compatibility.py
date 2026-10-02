from __future__ import annotations

import io
import socket
from types import SimpleNamespace

import pytest

from adaptorch_mcp import cli


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ([], "line"),
        (["--stdio-framing", "line"], "line"),
        (["--stdio-framing", "newline"], "line"),
        (["--stdio-framing", "content-length"], "content-length"),
    ],
)
def test_cli_framing_alias_only_normalizes_at_existing_boundary(monkeypatch, arguments, expected):
    def reject_network(*args, **kwargs):
        raise AssertionError("Network access is forbidden in the CLI alias fixture")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket, "getaddrinfo", reject_network)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    monkeypatch.setattr(cli.os, "environ", {"ADAPTORCH_CONTROL_PLANE_TOKEN": "ado_fixture"})
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(buffer=io.BytesIO()))
    monkeypatch.setattr(cli.sys, "stdout", SimpleNamespace(buffer=io.BytesIO()))
    calls = []
    monkeypatch.setattr(
        cli, "serve", lambda bridge, reader, writer, framing: calls.append(framing) or 0
    )

    assert cli.main(arguments) == 0
    assert calls == [expected]
