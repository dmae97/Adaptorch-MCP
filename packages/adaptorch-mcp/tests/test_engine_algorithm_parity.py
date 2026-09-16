# mypy: disable-error-code="import-not-found"
# pyright: reportMissingImports=false
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
from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args

import pytest
from adaptorch.mcp_server import AdaptOrchMCPServer

from adaptorch_mcp.first_run_receipt_output import (
    BUDGET_STATES,
    CLAIM_STATES,
    RECEIPT_VERDICTS,
    VERIFICATION_STATES,
    project_first_run_receipt,
)
from adaptorch_mcp.first_run_receipt_output import (
    CLAIM_BOUNDARY_FIELDS as RECEIPT_CLAIM_FIELDS,
)
from adaptorch_mcp.hardening import build_hardened_mcp_server
from adaptorch_mcp.orchestration_value_output import (
    CLAIM_BOUNDARY_FIELDS as WRAPPER_CLAIM_BOUNDARY,
)
from adaptorch_mcp.orchestration_value_output import (
    ORCHESTRATION_VALUE_ACTIONS as WRAPPER_ACTIONS,
)
from adaptorch_mcp.orchestration_value_output import (
    ORCHESTRATION_VALUE_VERDICTS as WRAPPER_VERDICTS,
)
from adaptorch_mcp.orchestration_value_output import (
    project_orchestration_value,
)
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
    ENGINE_ORCHESTRATION_VALUE_SURFACE = False
    DEPRECATED_SYNTHESIS_MODE_ALIASES = {}
    SELECTABLE_SYNTHESIS_MODES = ()
    SUPPORTED_SYNTHESIS_MODES = ()
    OUTPUT_EXTRACTOR_MODES = ()
    TOPOLOGY_VALUES = ()
    resolve_synthesis_mode = None
else:
    ENGINE_EXPORTS_SURFACE = True

try:
    from adaptorch.vera_types import (
        EvidenceCausality,
        VerificationDecision,
        VerificationOutcomeKind,
    )
    from adaptorch.verifier_registry import known_verifier_types
except ImportError:  # pragma: no cover - depends on the installed engine revision
    ENGINE_VERIFIER_SURFACE = False
    ENGINE_VERIFIER_TYPES: tuple[str, ...] = ()
    ENGINE_OUTCOME_KINDS: tuple[str, ...] = ()
    ENGINE_DECISIONS: tuple[str, ...] = ()
    ENGINE_CAUSALITIES: tuple[str, ...] = ()
else:
    ENGINE_VERIFIER_SURFACE = True
    ENGINE_VERIFIER_TYPES = tuple(known_verifier_types())
    ENGINE_OUTCOME_KINDS = tuple(kind.value for kind in VerificationOutcomeKind)
    ENGINE_DECISIONS = tuple(decision.value for decision in VerificationDecision)
    ENGINE_CAUSALITIES = tuple(causality.value for causality in EvidenceCausality)


def _literal_strings(annotation: Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in get_args(annotation):
        if isinstance(value, str):
            result.append(value)
        else:
            result.extend(_literal_strings(value))
    return tuple(dict.fromkeys(result))


try:
    from adaptorch.types import ServingSynthesisMode
except ImportError:  # Older engines have no serving-only selector.
    ENGINE_REQUEST_MODES = tuple(SELECTABLE_SYNTHESIS_MODES)
else:
    ENGINE_REQUEST_MODES = _literal_strings(ServingSynthesisMode)

try:
    from adaptorch.orchestration_value import (
        ORCHESTRATION_VALUE_ACTIONS,
        ORCHESTRATION_VALUE_CLAIM_BOUNDARY,
        ORCHESTRATION_VALUE_VERDICTS,
    )
except ImportError:  # pragma: no cover - depends on the installed engine revision
    ENGINE_ORCHESTRATION_VALUE_SURFACE = False
    ENGINE_VERDICTS: tuple[str, ...] = ()
    ENGINE_ACTIONS: tuple[str, ...] = ()
    ENGINE_CLAIM_BOUNDARY: dict[str, bool] = {}
else:
    ENGINE_ORCHESTRATION_VALUE_SURFACE = True
    ENGINE_VERDICTS = tuple(ORCHESTRATION_VALUE_VERDICTS)
    ENGINE_ACTIONS = tuple(ORCHESTRATION_VALUE_ACTIONS)
    ENGINE_CLAIM_BOUNDARY = dict(ORCHESTRATION_VALUE_CLAIM_BOUNDARY)

try:
    from adaptorch.b2c_first_run import (
        API_RECEIPT_KEYS,
        BudgetState,
        ClaimBoundary,
        ClaimBoundaryState,
        ReceiptVerdict,
        VerificationState,
        project_first_run_receipt_for_api,
    )
except ImportError:  # pragma: no cover - depends on the installed engine revision
    ENGINE_RECEIPT_SURFACE = False
    ENGINE_RECEIPT_VERDICTS: tuple[str, ...] = ()
    ENGINE_BUDGET_STATES: tuple[str, ...] = ()
    ENGINE_VERIFICATION_STATES: tuple[str, ...] = ()
    ENGINE_CLAIM_STATES: tuple[str, ...] = ()
    ENGINE_RECEIPT_KEYS: tuple[str, ...] = ()
    ENGINE_CLAIM_DEFAULTS: dict[str, bool] = {}
    ENGINE_RECEIPT_API_VIEW: dict[str, object] | None = None
else:
    ENGINE_RECEIPT_SURFACE = True
    ENGINE_RECEIPT_VERDICTS = tuple(item.value for item in ReceiptVerdict)
    ENGINE_BUDGET_STATES = tuple(item.value for item in BudgetState)
    ENGINE_VERIFICATION_STATES = tuple(item.value for item in VerificationState)
    ENGINE_CLAIM_STATES = tuple(item.value for item in ClaimBoundaryState)
    ENGINE_RECEIPT_KEYS = tuple(API_RECEIPT_KEYS)
    ENGINE_CLAIM_DEFAULTS = {
        "b2c_launch_ready": ClaimBoundary().b2c_launch_ready,
        "full50_claimed": ClaimBoundary().full50_claimed,
        "official_correctness_claimed": ClaimBoundary().official_correctness_claimed,
    }
    # Engine-authored view of persisted receipt state, including the internals
    # (artifact path, keyed digest) the engine projection is required to drop.
    ENGINE_RECEIPT_API_VIEW = project_first_run_receipt_for_api(
        {
            "enabled": True,
            "kind": "first_run",
            "artifact_path": "/srv/adaptorch/run_1/first_run_receipt.json",
            "prompt_hmac_sha256": "b" * 64,
            "summary": {
                "schema_version": 1,
                "verdict": ReceiptVerdict.DEGRADED.value,
                "budget_state": BudgetState.CAP_EXCEEDED.value,
                "verification_state": VerificationState.NOT_RUN.value,
                "claims": {
                    "state": ClaimBoundaryState.BETA_ONLY.value,
                    "positioning": ClaimBoundary().positioning,
                    "b2c_launch_ready": False,
                    "full50_claimed": False,
                    "official_correctness_claimed": False,
                },
            },
        }
    )

requires_engine_surface = pytest.mark.skipif(
    not ENGINE_EXPORTS_SURFACE,
    reason="installed adaptorch engine does not export the algorithm surface constants",
)
requires_verifier_surface = pytest.mark.skipif(
    not ENGINE_VERIFIER_SURFACE,
    reason="installed adaptorch engine does not export verifier/VERA surface constants",
)
requires_receipt_surface = pytest.mark.skipif(
    not ENGINE_RECEIPT_SURFACE,
    reason="installed adaptorch engine does not export the B2C receipt surface",
)
requires_orchestration_value_surface = pytest.mark.skipif(
    not ENGINE_ORCHESTRATION_VALUE_SURFACE,
    reason="installed adaptorch engine does not export the orchestration-value surface",
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _remote_server() -> Any:
    from adaptorch_mcp.hardening import HardenedMCPServer

    return HardenedMCPServer(
        backend=FakeBackend(),
        exposure_profile=REMOTE_EXPOSURE_PROFILE,
    )


def _decoded_tool_text(response: Mapping[str, Any]) -> dict[str, Any]:
    """Decode a tool result's single text block, failing loudly on a contract break."""
    text = response["result"]["content"][0]["text"]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        pytest.fail(f"tool result was not JSON: {exc}")
    assert isinstance(payload, dict)
    return payload


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
def test_exposed_synthesis_modes_match_engine_serving_modes() -> None:
    properties = _remote_run_schema()["properties"]

    assert properties["synthesis_mode"]["enum"] == list(ENGINE_REQUEST_MODES)
    assert properties["synthesis_mode"]["default"] in SUPPORTED_SYNTHESIS_MODES


@requires_engine_surface
def test_exposed_synthesis_mode_description_names_deprecated_aliases() -> None:
    description = _remote_run_schema()["properties"]["synthesis_mode"]["description"]

    assert resolve_synthesis_mode is not None
    for alias, target in DEPRECATED_SYNTHESIS_MODE_ALIASES.items():
        assert alias in description
        assert target in description
        assert resolve_synthesis_mode(alias) == target


@requires_engine_surface
def test_exposed_output_extractor_enum_matches_engine_extractors() -> None:
    properties = _remote_run_schema()["properties"]

    assert properties["output_extractor"]["enum"] == ["none", *OUTPUT_EXTRACTOR_MODES]


@requires_engine_surface
@pytest.mark.parametrize("mode", ENGINE_REQUEST_MODES or ["robust"])
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
    payload = _decoded_tool_text(response)

    projected = project_tool_output("adaptorch_capabilities", payload)

    assert projected is not None
    assert projected["synthesis_modes"] == list(ENGINE_REQUEST_MODES)
    assert projected["supported_synthesis_modes"] == list(SUPPORTED_SYNTHESIS_MODES)
    assert projected["deprecated_synthesis_mode_aliases"] == dict(DEPRECATED_SYNTHESIS_MODE_ALIASES)
    assert projected["topologies"] == list(TOPOLOGY_VALUES)
    assert projected["output_extractor_modes"] == list(OUTPUT_EXTRACTOR_MODES)
    for key, expected in (
        ("verifier_types", ENGINE_VERIFIER_TYPES),
        ("verification_outcome_kinds", ENGINE_OUTCOME_KINDS),
        ("verification_decisions", ENGINE_DECISIONS),
        ("evidence_causalities", ENGINE_CAUSALITIES),
    ):
        if key in payload:
            assert projected[key] == payload[key]
            if ENGINE_VERIFIER_SURFACE:
                assert projected[key] == list(expected)
        else:
            assert key not in projected  # Importable vocabulary is not an advertised capability.


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


def test_capabilities_projection_rejects_malformed_verifier_types() -> None:
    projected = project_tool_output(
        "adaptorch_capabilities",
        {
            "synthesis_modes": ["robust"],
            "verifier_types": [{"type": "hard_v3_independent"}],
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
@requires_verifier_surface
def test_docs_declare_the_engine_synthesis_mode_surface() -> None:
    text = (REPO_ROOT / "docs" / "tools.md").read_text(encoding="utf-8")

    for mode in SUPPORTED_SYNTHESIS_MODES:
        assert f"`{mode}`" in text
    for alias, target in DEPRECATED_SYNTHESIS_MODE_ALIASES.items():
        assert f"`{alias}`" in text
        assert f"`{target}`" in text
    for extractor in OUTPUT_EXTRACTOR_MODES:
        assert f"`{extractor}`" in text
    for item in (
        *ENGINE_VERIFIER_TYPES,
        *ENGINE_OUTCOME_KINDS,
        *ENGINE_DECISIONS,
        *ENGINE_CAUSALITIES,
    ):
        assert f"`{item}`" in text


def test_build_hardened_server_is_importable_for_surface_checks() -> None:
    assert callable(build_hardened_mcp_server)


@requires_receipt_surface
def test_wrapper_receipt_vocabulary_matches_the_engine() -> None:
    """The wrapper keeps literal copies so old engines still validate; they must agree."""
    assert RECEIPT_VERDICTS == ENGINE_RECEIPT_VERDICTS
    assert BUDGET_STATES == ENGINE_BUDGET_STATES
    assert VERIFICATION_STATES == ENGINE_VERIFICATION_STATES
    assert CLAIM_STATES == ENGINE_CLAIM_STATES


@requires_receipt_surface
def test_wrapper_publishes_no_claim_the_engine_would_not_make() -> None:
    assert RECEIPT_CLAIM_FIELDS == ENGINE_CLAIM_DEFAULTS


@requires_receipt_surface
def test_engine_receipt_projection_survives_the_wrapper_unchanged() -> None:
    """Engine-authored output, not a wrapper fixture: the two projections must agree."""
    assert ENGINE_RECEIPT_API_VIEW is not None
    assert set(ENGINE_RECEIPT_API_VIEW) <= set(ENGINE_RECEIPT_KEYS)
    assert "artifact_path" not in ENGINE_RECEIPT_API_VIEW
    assert "prompt_hmac_sha256" not in ENGINE_RECEIPT_API_VIEW
    assert project_first_run_receipt(ENGINE_RECEIPT_API_VIEW) == ENGINE_RECEIPT_API_VIEW


@requires_receipt_surface
def test_docs_declare_the_consumer_receipt_vocabulary() -> None:
    text = (REPO_ROOT / "docs" / "tools.md").read_text(encoding="utf-8")

    for verdict in ENGINE_RECEIPT_VERDICTS:
        assert f"`{verdict}`" in text
    for state in (*ENGINE_BUDGET_STATES, *ENGINE_VERIFICATION_STATES):
        assert f"`{state}`" in text


@requires_orchestration_value_surface
def test_docs_declare_the_engine_orchestration_vocabulary() -> None:
    text = (REPO_ROOT / "docs" / "tools.md").read_text(encoding="utf-8")

    for verdict in ENGINE_VERDICTS:
        assert f"`{verdict}`" in text
    for action in ENGINE_ACTIONS:
        assert f"`{action}`" in text
    for field in ENGINE_CLAIM_BOUNDARY:
        assert field in text


@requires_orchestration_value_surface
def test_wrapper_orchestration_vocabulary_matches_the_engine() -> None:
    """The wrapper keeps literal copies so old engines still validate; they must agree."""
    assert WRAPPER_VERDICTS == ENGINE_VERDICTS
    assert WRAPPER_ACTIONS == ENGINE_ACTIONS
    assert WRAPPER_CLAIM_BOUNDARY == ENGINE_CLAIM_BOUNDARY


@requires_orchestration_value_surface
def test_capabilities_projection_publishes_the_orchestration_vocabulary() -> None:
    server = AdaptOrchMCPServer(backend=FakeBackend())
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "adaptorch_capabilities", "arguments": {}},
        }
    )
    assert response is not None
    payload = _decoded_tool_text(response)

    projected = project_tool_output("adaptorch_capabilities", payload)

    assert projected is not None
    assert projected["orchestration_value_verdicts"] == list(ENGINE_VERDICTS)
    assert projected["orchestration_value_actions"] == list(ENGINE_ACTIONS)


@requires_orchestration_value_surface
def test_local_route_topology_prices_replication_end_to_end() -> None:
    """Full profile: the router's own decision arrives with its cost disclosure."""
    server = AdaptOrchMCPServer(backend=FakeBackend())
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "adaptorch_route_topology",
                "arguments": {
                    "subtasks": [{"id": "v1", "description": "one arithmetic question"}],
                    "prefer_ensemble_singleton": True,
                },
            },
        }
    )
    assert response is not None
    payload = _decoded_tool_text(response)

    projected = project_tool_output("adaptorch_route_topology", payload)

    assert projected is not None
    advisory = projected["orchestration_value"]
    assert advisory["verdict"] == "replication_unproven"
    assert advisory["recommended_action"] == "measure_first"
    assert advisory["claim_boundary"] == dict(WRAPPER_CLAIM_BOUNDARY)
    # Live engine payload, not a fixture: the projection must not mangle it.
    assert (
        project_orchestration_value(payload["orchestration_value"])
        == (payload["orchestration_value"])
    )


class _RecordingBackend(FakeBackend):
    """FakeBackend drops the payload; the tri-state contract is carried in it."""

    def __init__(self) -> None:
        self.payloads: list[Mapping[str, Any]] = []

    def run_task(self, *, payload: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.payloads.append(payload)
        return super().run_task(payload=payload, **kwargs)

    def run_task_and_collect(self, *, payload: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        # adaptorch_run waits for a terminal state by default, so this is the
        # path a plain call actually takes.
        self.payloads.append(payload)
        return super().run_task_and_collect(payload=payload, **kwargs)


def _remote_singleton_hint(arguments: Mapping[str, Any]) -> Any:
    """Run through the remote profile; return the forwarded hint or the error code."""
    from adaptorch_mcp.hardening import HardenedMCPServer

    backend = _RecordingBackend()
    server = HardenedMCPServer(
        backend=backend,
        exposure_profile=REMOTE_EXPOSURE_PROFILE,
    )
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "adaptorch_run",
                "arguments": {
                    "payload": {"subtasks": [{"id": "v1", "description": "x"}]},
                    **arguments,
                },
            },
        }
    )
    assert response is not None
    if "error" in response:
        return response["error"]["code"]
    metadata = backend.payloads[0]["metadata"]
    assert isinstance(metadata, Mapping)
    return metadata.get("mcp")


def test_remote_profile_carries_every_tristate_singleton_value() -> None:
    """The engine's hint is tri-state; the hardened surface must not flatten it.

    `false` disables the ensemble auto preference, omission leaves it in charge,
    and an explicit `null` says so on the record. A wrapper that coerced the
    argument to a plain bool would turn everyone who omitted it into someone who
    opted out, and no schema check would notice.
    """
    assert _remote_singleton_hint({"prefer_ensemble_singleton": True}) == {
        "prefer_ensemble_singleton": True
    }
    assert _remote_singleton_hint({"prefer_ensemble_singleton": False}) == {
        "prefer_ensemble_singleton": False
    }
    assert _remote_singleton_hint({"prefer_ensemble_singleton": None}) == {
        "prefer_ensemble_singleton": None
    }
    assert _remote_singleton_hint({}) is None
    # Invalid params, not a silent coercion to truthiness.
    assert _remote_singleton_hint({"prefer_ensemble_singleton": "yes"}) == -32602


def test_remote_run_schema_declares_the_tristate_singleton() -> None:
    """A caller reads the schema before calling, so it has to state all three."""
    hint = _remote_run_schema()["properties"]["prefer_ensemble_singleton"]

    assert hint["type"] == ["boolean", "null"]
    # Not `default: false`, which would advertise omission as an opt-out.
    assert hint["default"] is None
    description = hint["description"].lower()
    assert "false" in description
    assert "auto" in description


def test_docs_declare_the_tristate_singleton_contract() -> None:
    """Docs are a surface too: they must not describe a boolean flag."""
    for relative in ("docs/tools.md", "docs/configuration.md", "README.md"):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        stated = [
            line
            for line in text.splitlines()
            if "prefer_ensemble_singleton" in line and "`false`" in line and "`null`" in line
        ]
        assert stated, f"{relative} does not state the tri-state singleton contract"


def test_remote_profile_still_withholds_the_local_router() -> None:
    """The advisory is additive; it must not widen the remote exposure surface."""
    response = _remote_server().handle_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "adaptorch_route_topology",
                "arguments": {"subtasks": [{"id": "v1", "description": "x"}]},
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32601
