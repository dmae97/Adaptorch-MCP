from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from adaptorch_client import AdaptOrchClient, ClientConfig, PollPolicy, Run, RunPollResult, polling
from adaptorch_client import client as client_module
from adaptorch_client.transport import HTTPTransport, RequestSpec
from cli_test_support import CliRunner

from adaptorch_cli import cli


@pytest.mark.parametrize(
    ("reason", "status", "expected"),
    [
        ("terminal", "SUCCEEDED", 0),
        ("terminal", "sUcCeEdEd", 0),
        ("terminal", "FAILED", 8),
        ("terminal", "failed", 8),
        ("terminal", "CANCELLED", 9),
        ("terminal", "cancelled", 9),
        ("deadline", "RUNNING", 10),
        ("deadline", "SUCCEEDED", 10),
        ("deadline", "FAILED", 10),
        ("poll_limit", "RUNNING", 10),
        ("unsupported_status", "INCONCLUSIVE", 10),
        ("unsupported_status", "FUTURE_STATUS", 10),
        ("future_reason", "SUCCEEDED", 10),
        ("terminal", "RUNNING", 10),
        ("terminal", "FUTURE_STATUS", 10),
    ],
)
def test_wait_exit_preserves_observation_and_never_resubmits(
    run_cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    status: str,
    expected: int,
) -> None:
    monkeypatch.setenv("FAKE_WAIT_REASON", reason)
    monkeypatch.setenv("FAKE_RUN_STATUS", status)
    result = run_cli(["run", "wait", "run-1"])

    assert result.returncode == expected
    assert json.loads(result.stdout) == {
        "reason": reason,
        "polls": 1,
        "elapsed_seconds": 0.01,
        "run": {"id": "run-1", "status": status},
    }
    assert result.stdout.count("\n") == 1
    assert result.stderr == ""
    methods = [json.loads(line)["method"] for line in result.client_log.splitlines()]
    assert methods == ["init", "wait_for_run"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"reason": None, "run": {"status": "SUCCEEDED"}},
        {"reason": 1, "run": {"status": "SUCCEEDED"}},
        {"reason": "future_reason", "run": {"status": "SUCCEEDED"}},
        {"reason": "terminal"},
        {"reason": "terminal", "run": None},
        {"reason": "terminal", "run": []},
        {"reason": "terminal", "run": {}},
        {"reason": "terminal", "run": {"status": None}},
        {"reason": "terminal", "run": {"status": 1}},
        {"reason": "terminal", "run": {"status": ""}},
        {"reason": "terminal", "run": {"data": {"status": "SUCCEEDED"}}},
        {"reason": "deadline"},
        {"reason": "poll_limit"},
        {"reason": "unsupported_status"},
    ],
)
def test_wait_unknown_or_missing_observation_is_inconclusive(
    payload: cli.JSONMapping,
) -> None:
    assert cli._wait_status_exit(payload) == 10


def test_wait_lifecycle_does_not_claim_result_correctness() -> None:
    assert cli._wait_status_exit(
        {"reason": "terminal", "run": {"status": "SUCCEEDED", "result_status": "FAILED"}}
    ) == 0


def test_wait_does_not_reinterpret_server_cancellation_encoding() -> None:
    assert cli._wait_status_exit(
        {"reason": "terminal", "run": {"status": "FAILED", "error_class": "CANCELLED"}}
    ) == 8


@pytest.mark.parametrize(
    ("status", "reason", "expected", "timeout", "latency", "count"),
    [
        ("SUCCEEDED", "terminal", 0, "5", 0.0, 1),
        ("FAILED", "terminal", 8, "5", 0.0, 1),
        ("CANCELLED", "terminal", 9, "5", 0.0, 1),
        ("RUNNING", "deadline", 10, "0.5", 0.0, 1),
        # The read budget follows --timeout, so a long wait ends at its deadline
        # (200 reads at t=0..199) instead of a fixed 100-read cut-off.
        ("RUNNING", "deadline", 10, "200", 0.0, 200),
        ("NEW_STATUS", "unsupported_status", 10, "5", 0.0, 1),
        ("INCONCLUSIVE", "unsupported_status", 10, "5", 0.0, 1),
        ("SUCCEEDED", "deadline", 10, "0.5", 0.5, 1),
    ],
)
def test_wait_uses_real_sdk_polling_without_writing_or_resubmitting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status: str,
    reason: str,
    expected: int,
    timeout: str,
    latency: float,
    count: int,
) -> None:
    elapsed = 0.0
    requests: list[RequestSpec] = []

    def clock() -> float:
        return elapsed

    def sleep(duration: float) -> None:
        nonlocal elapsed
        elapsed += duration

    def request(_transport: HTTPTransport, spec: RequestSpec) -> cli.JSONMapping:
        nonlocal elapsed
        requests.append(spec)
        elapsed += latency
        return {"run_id": "run-1", "status": status}

    def poll(fetch: Callable[[float], Run], policy: PollPolicy) -> RunPollResult:
        return polling.wait_for_run(fetch, policy, clock=clock, sleep=sleep)

    client = AdaptOrchClient(ClientConfig("https://api.example.test", "ado_test"))
    monkeypatch.setenv("ADAPTORCH_CONFIG_DIR", str(tmp_path / "isolated-config"))
    monkeypatch.setattr(cli, "_require_client", lambda _api_url: client)
    monkeypatch.setattr(HTTPTransport, "request", request)
    monkeypatch.setattr(client_module, "poll_run", poll)

    code = cli.main(["run", "wait", "run-1", "--timeout", timeout, "--interval", "1"])

    captured = capsys.readouterr()
    assert code == expected
    assert json.loads(captured.out) == {
        "reason": reason,
        "polls": count,
        "elapsed_seconds": elapsed,
        "run": {"run_id": "run-1", "status": status},
    }
    assert captured.out.count("\n") == 1
    assert captured.err == ""
    assert len(requests) == count
    assert all((spec.method, spec.path) == ("GET", "/v1/runs/run-1") for spec in requests)
    assert all(spec.payload is None and spec.provider_credential is None for spec in requests)


@pytest.mark.parametrize(
    ("status", "expected"),
    [("SUCCEEDED", 0), ("RUNNING", 0), ("NEW_STATUS", 0), ("FAILED", 8), ("CANCELLED", 9)],
)
def test_get_retains_its_mapping_with_additive_wait_like_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status: str,
    expected: int,
) -> None:
    payload: cli.JSONMapping = {"run_id": "run-1", "status": status, "reason": "deadline"}
    monkeypatch.setenv("ADAPTORCH_CONFIG_DIR", str(tmp_path / "isolated-config"))
    monkeypatch.setattr(cli, "_execute", lambda *_args: (payload, True))

    assert cli.main(["run", "get", "run-1"]) == expected
    captured = capsys.readouterr()
    assert json.loads(captured.out) == payload
    assert captured.err == ""


def test_explicit_max_polls_still_bounds_the_wait(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    elapsed = 0.0
    requests: list[RequestSpec] = []

    def sleep(duration: float) -> None:
        nonlocal elapsed
        elapsed += duration

    def request(_transport: HTTPTransport, spec: RequestSpec) -> cli.JSONMapping:
        requests.append(spec)
        return {"run_id": "run-1", "status": "RUNNING"}

    def poll(fetch: Callable[[float], Run], policy: PollPolicy) -> RunPollResult:
        return polling.wait_for_run(fetch, policy, clock=lambda: elapsed, sleep=sleep)

    client = AdaptOrchClient(ClientConfig("https://api.example.test", "ado_test"))
    monkeypatch.setenv("ADAPTORCH_CONFIG_DIR", str(tmp_path / "isolated-config"))
    monkeypatch.setattr(cli, "_require_client", lambda _api_url: client)
    monkeypatch.setattr(HTTPTransport, "request", request)
    monkeypatch.setattr(client_module, "poll_run", poll)

    code = cli.main(
        ["run", "wait", "run-1", "--timeout", "300", "--interval", "2", "--max-polls", "7"]
    )

    assert code == 10
    assert json.loads(capsys.readouterr().out)["reason"] == "poll_limit"
    assert len(requests) == 7


@pytest.mark.parametrize(
    ("timeout", "interval", "expected"),
    [(120.0, 1.0, 121), (300.0, 2.0, 151), (0.5, 1.0, 2), (5.0, 0.3, 18)],
)
def test_default_read_budget_covers_the_whole_timeout(
    timeout: float, interval: float, expected: int
) -> None:
    assert cli._wait_poll_limit(timeout, interval) == expected


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "many"])
def test_max_polls_rejects_non_positive_integers(run_cli: CliRunner, value: str) -> None:
    result = run_cli(["run", "wait", "run-1", "--max-polls", value])

    assert result.returncode == 2
    assert "wait_for_run" not in result.client_log
