"""Read-only polling is a bounded observation loop, never a resubmission loop."""

from __future__ import annotations

import pytest

from adaptorch_client import Run


def _run(status: str) -> Run:
    return Run.from_payload({"run_id": "r1", "status": status, "result_status": "DEGRADED"})


class Clock:
    def __init__(self) -> None:
        self.now: float = 0.0

    def read(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_polling_stops_on_terminal_without_changing_result_status() -> None:
    from adaptorch_client.polling import PollPolicy, wait_for_run

    clock = Clock()
    statuses = iter(("QUEUED", "RUNNING", "SUCCEEDED"))
    budgets: list[float] = []

    def fetch(remaining: float) -> Run:
        budgets.append(remaining)
        return _run(next(statuses))

    result = wait_for_run(
        fetch, PollPolicy(timeout_seconds=10), clock=clock.read, sleep=clock.sleep
    )
    assert result.reason.value == "terminal"
    assert result.polls == 3 and result.run is not None
    assert result.run.result_status == "DEGRADED"
    assert budgets == [10, 9, 8]


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED", "succeeded"])
def test_every_documented_terminal_stops_after_one_read(status: str) -> None:
    from adaptorch_client.polling import PollPolicy, wait_for_run

    result = wait_for_run(lambda remaining: _run(status), PollPolicy())
    assert result.polls == 1 and result.reason.value == "terminal"


def test_unknown_status_stops_without_guessing_terminal_success() -> None:
    from adaptorch_client.polling import PollPolicy, wait_for_run

    result = wait_for_run(lambda remaining: _run("NEW_SERVER_STATE"), PollPolicy())
    assert result.polls == 1 and result.reason.value == "unsupported_status"


def test_poll_count_limit_never_turns_into_a_submission_or_retry() -> None:
    from adaptorch_client.polling import PollPolicy, wait_for_run

    clock = Clock()
    calls: list[float] = []

    def fetch(remaining: float) -> Run:
        calls.append(remaining)
        return _run("RUNNING")

    result = wait_for_run(fetch, PollPolicy(max_polls=2), clock=clock.read, sleep=clock.sleep)
    assert len(calls) == 2 and result.reason.value == "poll_limit"


def test_late_terminal_observation_stays_deadline_limited() -> None:
    from adaptorch_client.polling import PollPolicy, wait_for_run

    clock = Clock()

    def fetch(remaining: float) -> Run:
        clock.now += remaining
        return _run("SUCCEEDED")

    result = wait_for_run(fetch, PollPolicy(), clock=clock.read, sleep=clock.sleep)
    assert result.reason.value == "deadline" and result.polls == 1


def test_transport_error_is_not_hidden_or_automatically_retried() -> None:
    from adaptorch_client import AdaptOrchAPIError
    from adaptorch_client.polling import PollPolicy, wait_for_run

    calls = 0

    def fetch(_remaining: float) -> Run:
        nonlocal calls
        calls += 1
        raise AdaptOrchAPIError("synthetic unavailable")

    with pytest.raises(AdaptOrchAPIError):
        _ = wait_for_run(fetch, PollPolicy())
    assert calls == 1


@pytest.mark.parametrize("seconds", [True, 0, float("inf")])
def test_invalid_poll_timeout_is_rejected(seconds: float) -> None:
    from adaptorch_client.polling import PollPolicy

    with pytest.raises(ValueError):
        _ = PollPolicy(timeout_seconds=seconds)


@pytest.mark.parametrize("count", [True, 0])
def test_invalid_poll_count_is_rejected(count: int) -> None:
    from adaptorch_client.polling import PollPolicy

    with pytest.raises(ValueError):
        _ = PollPolicy(max_polls=count)


def test_invalid_poll_interval_is_rejected() -> None:
    from adaptorch_client.polling import PollPolicy

    with pytest.raises(ValueError):
        _ = PollPolicy(interval_seconds=-1)
