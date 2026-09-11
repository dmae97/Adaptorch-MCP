"""Parity tests binding the public MCP surface to the installed engine algorithm.

The wrapper never reimplements routing or synthesis. These tests fail closed when
the exposed surface drifts from the algorithm constants of the installed
`adaptorch` engine (synthesis modes, deprecated aliases, topologies, extractors).

Engines older than the exported surface constants cannot be compared, so those checks
skip with an explicit reason instead of reporting false drift. Install a current engine
(`make engine-local ENGINE_PATH=../adaptorch`) to activate them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

import pytest
from adaptorch.mcp_server import AdaptOrchMCPServer

from adaptorch_mcp.hardening import build_hardened_mcp_server
from adaptorch_mcp.output_schema import project_tool_output
from adaptorch_mcp.security_policy import REMOTE_EXPOSURE_PROFILE
from mcp_test_support import FakeBackend

try:
    from adaptorch.synthesis import (
        DEPRECATED_SYNTHESIS_MODE_ALIASES,
        SELECTABLE_SYNTHESIS_MODES,
        SUPPORTED_SYNTHESIS_MODES,
        resolve_synthesis_mode,
    )
    from adaptorch.types import OUTPUT_EXTRACTOR_MODES, TOPOLOGY_VALUES
except ImportError:  # pragma: no cover - depends on the installed engine revision
    ENGINE_EXPORTS_SURFACE = False
    DEPRECATED_SYNTHESIS_MODE_ALIASES = {}
    SELECTABLE_SYNTHESIS_MODES = ()
    SUPPORTED_SYNTHESIS_MODES = ()
    OUTPUT_EXTRACTOR_MODES = ()
    TOPOLOGY_VALUES = ()
    resolve_synthesis_mode = None
else:
    ENGINE_EXPORTS_SURFACE = True

try:
    from adaptorch.types import ServingSynthesisMode
except ImportError:
    SERVING_SYNTHESIS_MODES = SELECTABLE_SYNTHESIS_MODES
else:
    # ServingSynthesisMode is a union of the engine Literal and the auto Literal.
    SERVING_SYNTHESIS_MODES = tuple(
        value for variant in get_args(ServingSynthesisMode) for value in get_args(variant)
    )

requires_engine_surface = pytest.mark.skipif(
    not ENGINE_EXPORTS_SURFACE,
    reason="installed adaptorch engine does not export the algorithm surface constants",
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _remote_server() -> Any:
    from adaptorch_mcp.hardening import HardenedMCPServer

    return HardenedMCPServer(
        backend=FakeBackend(),
        exposure_profile=REMOTE_EXPOSURE_PROFILE,
    )


def _remote_run_schema() -> dict[str, Any]:
    response = _remote_server().handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )
    assert response is not None
    tools = response["result"]["tools"]
    run_tool = next(tool for tool in tools if tool["name"] == "adaptorch_run")
    schema: dict[str, Any] = run_tool["inputSchema"]
    return schema


@requires_engine_surface
def test_exposed_synthesis_modes_match_engine_selectable_modes() -> None:
    properties = _remote_run_schema()["properties"]

    assert properties["synthesis_mode"]["enum"] == list(SERVING_SYNTHESIS_MODES)
    assert properties["synthesis_mode"]["default"] in SUPPORTED_SYNTHESIS_MODES


@requires_engine_surface
def test_exposed_synthesis_mode_description_names_deprecated_aliases() -> None:
    description = _remote_run_schema()["properties"]["synthesis_mode"]["description"]

    for alias, target in DEPRECATED_SYNTHESIS_MODE_ALIASES.items():
        assert alias in description
        assert target in description
        assert resolve_synthesis_mode(alias) == target


@requires_engine_surface
def test_exposed_output_extractor_enum_matches_engine_extractors() -> None:
    properties = _remote_run_schema()["properties"]

    assert properties["output_extractor"]["enum"] == ["none", *OUTPUT_EXTRACTOR_MODES]


@requires_engine_surface
@pytest.mark.parametrize("mode", SERVING_SYNTHESIS_MODES or ["robust"])
def test_remote_profile_accepts_every_engine_selectable_mode(mode: str) -> None:
    response = _remote_server().handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "adaptorch_run",
                "arguments": {
                    "prompt": "align the wrapper",
                    "synthesis_mode": mode,
                    "wait_for_terminal": False,
                },
            },
        }
    )

    assert response is not None
    assert "error" not in response


def test_remote_profile_rejects_modes_the_engine_does_not_accept() -> None:
    response = _remote_server().handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "adaptorch_run",
                "arguments": {"prompt": "x", "synthesis_mode": "direct"},
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32602


@requires_engine_surface
def test_capabilities_projection_preserves_engine_algorithm_surface() -> None:
    server = AdaptOrchMCPServer(backend=FakeBackend())
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "adaptorch_capabilities", "arguments": {}},
        }
    )
    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])

    projected = project_tool_output("adaptorch_capabilities", payload)

    assert projected is not None
    assert projected["synthesis_modes"] == list(SERVING_SYNTHESIS_MODES)
    assert projected["supported_synthesis_modes"] == list(SUPPORTED_SYNTHESIS_MODES)
    assert projected["deprecated_synthesis_mode_aliases"] == dict(DEPRECATED_SYNTHESIS_MODE_ALIASES)
    assert projected["topologies"] == list(TOPOLOGY_VALUES)
    assert projected["output_extractor_modes"] == list(OUTPUT_EXTRACTOR_MODES)


def test_run_projection_preserves_requested_and_selected_serving_modes() -> None:
    payload = {
        "run_id": "fixture-run",
        "status": "QUEUED",
        "model": "Tenant-Selected-Model",
        "model_selection_source": "tenant_history",
        "synthesis_mode_requested": "auto",
        "synthesis_mode_used": "robust_lite",
    }
    assert project_tool_output("adaptorch_run", payload) == payload


def test_capabilities_projection_tolerates_parent_without_algorithm_surface() -> None:
    projected = project_tool_output(
        "adaptorch_capabilities",
        {
            "synthesis_modes": ["paper", "robust"],
            "connectors": ["mcp"],
            "cloud_plan_catalog": {
                "schemaVersion": "1",
                "catalogVersion": "1",
                "billingCycle": "monthly",
                "currency": "USD",
                "sourceOfTruth": ["adaptorch.com"],
                "notes": [],
                "plans": [],
            },
            "server_capabilities": {
                "tools": True,
                "resources": True,
                "prompts": True,
                "logging": True,
            },
        },
    )

    assert projected is not None
    assert "supported_synthesis_modes" not in projected


def test_capabilities_projection_rejects_malformed_algorithm_surface() -> None:
    projected = project_tool_output(
        "adaptorch_capabilities",
        {
            "synthesis_modes": ["robust"],
            "supported_synthesis_modes": [{"mode": "robust"}],
            "connectors": ["mcp"],
            "cloud_plan_catalog": {
                "schemaVersion": "1",
                "catalogVersion": "1",
                "billingCycle": "monthly",
                "currency": "USD",
                "sourceOfTruth": ["adaptorch.com"],
                "notes": [],
                "plans": [],
            },
            "server_capabilities": {
                "tools": True,
                "resources": True,
                "prompts": True,
                "logging": True,
            },
        },
    )

    assert projected is None


@requires_engine_surface
def test_docs_declare_the_engine_synthesis_mode_surface() -> None:
    text = (REPO_ROOT / "docs" / "tools.md").read_text(encoding="utf-8")

    for mode in SUPPORTED_SYNTHESIS_MODES:
        assert f"`{mode}`" in text
    for alias, target in DEPRECATED_SYNTHESIS_MODE_ALIASES.items():
        assert f"`{alias}`" in text
        assert f"`{target}`" in text
    for extractor in OUTPUT_EXTRACTOR_MODES:
        assert f"`{extractor}`" in text


def test_build_hardened_server_is_importable_for_surface_checks() -> None:
    assert callable(build_hardened_mcp_server)
