"""Bounded read-only run observation; never submits, cancels or retries a failed request."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from threading import TIMEOUT_MAX
from typing import Final

from adaptorch_client.errors import AdaptOrchAPIError
from adaptorch_client.models import Run

# User API v1 liveness vocabulary. Unknown additive statuses stop, rather than spin.
_TERMINAL: Final = frozenset({"succeeded", "failed", "cancelled"})
_PENDING: Final = frozenset({"queued", "running", "cancelling"})


@dataclass(frozen=True, slots=True)
class PollPolicy:
    timeout_seconds: float = 120.0
    interval_seconds: float = 1.0
    max_polls: int = 100

    def __post_init__(self) -> None:
        for name, value in (
            ("timeout_seconds", self.timeout_seconds),
            ("interval_seconds", self.interval_seconds),
        ):
            if (
                type(value) not in (int, float)
                or not 0 <= value <= TIMEOUT_MAX
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite and within the platform wait limit")
        if self.timeout_seconds == 0:
            raise ValueError("timeout_seconds must be positive")
        if type(self.max_polls) is not int or self.max_polls < 1:
            raise ValueError("max_polls must be a positive integer")


class PollStopReason(StrEnum):
    TERMINAL = "terminal"
    DEADLINE = "deadline"
    POLL_LIMIT = "poll_limit"
    UNSUPPORTED_STATUS = "unsupported_status"


@dataclass(frozen=True, slots=True)
class RunPollResult:
    run: Run | None = field(repr=False)
    polls: int
    reason: PollStopReason
    elapsed_seconds: float


def wait_for_run(
    fetch: Callable[[float], Run],
    policy: PollPolicy,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> RunPollResult:
    """Pass remaining time to each read, stop between calls, retain the last observation.

    The HTTP layer must honor its own timeout. This loop cannot forcibly interrupt
    a blocking transport or cancel server-side execution. Transport errors propagate
    immediately; the caller chooses whether to attempt a later read.
    """
    start = last = clock()
    if not math.isfinite(start):
        raise AdaptOrchAPIError("Polling clock is invalid")
    deadline = start + policy.timeout_seconds
    run: Run | None = None
    polls = 0

    def now() -> float:
        nonlocal last
        value = clock()
        if not math.isfinite(value) or value < last:
            raise AdaptOrchAPIError("Polling clock is invalid")
        last = value
        return value

    for _ in range(policy.max_polls):
        remaining = deadline - now()
        if remaining <= 0:
            return RunPollResult(run, polls, PollStopReason.DEADLINE, last - start)
        run = fetch(remaining)
        polls += 1
        elapsed = now() - start
        if last >= deadline:
            return RunPollResult(run, polls, PollStopReason.DEADLINE, elapsed)
        status = run.status.lower()
        if status in _TERMINAL:
            return RunPollResult(run, polls, PollStopReason.TERMINAL, elapsed)
        if status not in _PENDING:
            return RunPollResult(run, polls, PollStopReason.UNSUPPORTED_STATUS, elapsed)
        if polls < policy.max_polls:
            sleep(min(policy.interval_seconds, deadline - last))
    return RunPollResult(run, polls, PollStopReason.POLL_LIMIT, last - start)
