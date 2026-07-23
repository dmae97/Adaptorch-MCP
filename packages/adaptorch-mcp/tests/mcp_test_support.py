from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from adaptorch.types import SynthesisMode


class FakeBackend:
    def run_task(
        self,
        *,
        payload: Mapping[str, Any],
        synthesis_mode: SynthesisMode = "robust",
        model: str | None = None,
        budget_policy: Mapping[str, int | float | str | bool] | None = None,
        trace: bool = False,
    ) -> dict[str, Any]:
        del payload, synthesis_mode, model, budget_policy, trace
        return {"run_id": "r1", "status": "QUEUED", "diagnostics": {"width": 2}}

    def run_task_and_collect(
        self,
        *,
        payload: Mapping[str, Any],
        synthesis_mode: SynthesisMode = "robust",
        model: str | None = None,
        budget_policy: Mapping[str, int | float | str | bool] | None = None,
        trace: bool = False,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
    ) -> dict[str, Any]:
        del (
            payload,
            synthesis_mode,
            model,
            budget_policy,
            trace,
            timeout_seconds,
            poll_interval_seconds,
        )
        return {
            "run_id": "r1",
            "status": "SUCCEEDED",
            "topology": "hybrid",
            "diagnostics": {"topology_evidence": {"reason": "threshold"}},
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "status": "SUCCEEDED",
            "topology": "hybrid",
            "diagnostics": {"reason": "private threshold"},
        }

    def get_artifacts(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "artifacts": [],
            "diagnostics": {"routing_scores": {"hybrid": 0.9}},
        }
