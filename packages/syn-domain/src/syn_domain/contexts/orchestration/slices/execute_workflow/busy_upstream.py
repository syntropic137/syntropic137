"""When a failed agent phase gets another attempt, and how long it waits (#1303).

A phase that ends because the model provider was BUSY has not told us anything
about the change, the workspace or the platform. The request was well-formed;
the upstream simply had no capacity for it this second:

    Agent failed: codex reported: Selected model is at capacity.
    Please try a different model. (phase=verify, exit_code=1)

That failure used to end the execution, discarding every phase that had already
completed and been paid for - twice in one window, $18.63, both at `verify`,
which is the third of four phases. The blip lasts seconds; the loss is total.

Three ways to get this wrong, and they pull in different directions:

  - Retry too much. A second attempt at a login that is not valid, a prompt the
    provider refused, or a quota that resets next month will fail exactly the
    same way, having spent the phase's budget again. One loss becomes several.
    So a reason qualifies only by being, IN FULL, one of the fixed strings the
    stream processors normalise a busy upstream into - never by containing one.
    `Rate limit reached; quota resets next month` contains "rate limit" and is
    permanent; `Invalid request: rate_limit must be positive` contains it and
    is about the request. Substring matching cannot tell any of them apart, and
    an agent that merely QUOTES one of these sentences would forge the signal.
  - Retry past the budget. Three attempts at a 3600-second phase used to be
    three fresh 3600-second clocks, so a phase that could not exceed an hour
    could run for three and bill for three. The whole sequence - every attempt
    and every backoff between them - is spent from ONE deadline, fixed before
    the first attempt starts. See `PhaseAttempts`.
  - Hide a permanent failure. A retry that runs out of attempts and then
    reports something other than the original cause is worse than no retry:
    the execution still fails, but the reason it failed is now a story about
    retrying. So this module decides only whether to go again. It never
    touches, wraps or replaces the reason, and the caller fails with exactly
    the reason it already had.

DELIBERATELY NOT HERE: HTTP 5xx / `api_error`. A server error may be transient
and may be a persistent rejection wearing a 500, and nothing in the message
distinguishes them. The class this exists for - "we are full, come back" - is
one the upstream states plainly, so the list only needs the plain statements.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    codex_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    ApiErrorType,
    api_error_label,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

#: The claude-side busy faults, each paired with the HTTP status the provider
#: sends it with. Not spelled out as prose: `api_error_label` is where a fault
#: gets its human wording, so asking it for the wording is the only way this
#: list cannot disagree with the string a stream processor actually produced.
_BUSY_API_ERRORS: tuple[tuple[ApiErrorType, str], ...] = (
    (ApiErrorType.OVERLOADED, "529"),
    (ApiErrorType.RATE_LIMIT, "429"),
)

#: The one sentence codex says about its own capacity.
#:
#: Unlike claude's, this is NOT normalised by the codex adapter: that adapter
#: forwards whatever the CLI put in the event verbatim, through
#: `codex_fault_reason`, and has no label registry to ask. So this literal is
#: the sentence observed in #1303 and nothing stronger - codex does not promise
#: to keep saying it. That makes the list narrow rather than loose, which is
#: the right way for it to be wrong: a phrasing not on it fails on attempt one,
#: exactly as every phase did before this module existed.
_CODEX_AT_CAPACITY = "Selected model is at capacity. Please try a different model."

#: Every reason that IS an upstream reporting its own capacity, spelled exactly
#: as the stream processors spell it. Membership is by equality, not by
#: containment - see the module docstring for what containment let through.
_BUSY_UPSTREAM_REASONS: frozenset[str] = frozenset(
    [api_error_label(error_type) for error_type, _ in _BUSY_API_ERRORS]
    + [api_error_label(error_type, status) for error_type, status in _BUSY_API_ERRORS]
    + [codex_fault_reason(_CODEX_AT_CAPACITY)]
)

#: The least time an attempt may be given and still be worth starting. Below
#: this, launching the container and starting the harness is all the budget
#: buys: the attempt would be killed during its own setup and report a timeout
#: in place of the upstream's reason, replacing a cause an operator can act on
#: with one they cannot.
_MIN_USEFUL_ATTEMPT_SECONDS: float = 30.0


def _upstream_was_busy(reason: str | None) -> bool:
    """Whether ``reason`` is, in full, the upstream reporting its own capacity."""
    return reason in _BUSY_UPSTREAM_REASONS


@dataclass(frozen=True)
class AttemptClock:
    """Telling the time, and spending it.

    Both halves together because they have to agree: the backoff is charged to
    the same deadline the attempts are, so a test that fakes the sleeping and
    not the reading would observe a budget nothing ever drew from.
    """

    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


class PhaseAttempts:
    """The attempts one phase has left, and the single deadline they share.

    Created by `UpstreamRetryPolicy.begin` before attempt one and consulted
    after each failure. `seconds_left` is what the next attempt may take;
    `wait_before_retry` answers whether there is a next attempt at all.

    The deadline is fixed at construction and never extended. Every attempt and
    every backoff is drawn from it, so three attempts cost a phase's configured
    time between them - not three times it, which is what a per-attempt timeout
    bought and billed for.
    """

    def __init__(
        self, *, policy: UpstreamRetryPolicy, timeout_seconds: float, clock: AttemptClock
    ) -> None:
        self._policy = policy
        self._clock = clock
        self._deadline = clock.monotonic() + timeout_seconds
        self._attempt = 1

    @property
    def seconds_left(self) -> float:
        """Time the attempt about to start may take, never below zero."""
        return max(self._deadline - self._clock.monotonic(), 0.0)

    @property
    def attempt(self) -> int:
        """Which attempt is running, 1-based. For logging, not for deciding."""
        return self._attempt

    @property
    def max_attempts(self) -> int:
        """The bound this phase was started under. For logging, not for deciding."""
        return self._policy.max_attempts

    async def wait_before_retry(self, *, reason: str | None, work_done: bool) -> bool:
        """Sleep out the backoff and report whether the failed attempt gets a successor.

        ``reason`` is what the attempt that just failed reported; ``work_done``
        is whether that attempt (or any before it) had already got somewhere -
        see `agent_attempts`.

        False means this failure is final and the caller must report ``reason``
        as it stands. It says nothing about WHY it is final - a genuine error, a
        spent budget, an expired deadline and an attempt that had already
        started working all end the run the same way, with the same cause, and a
        caller that branched on the difference would be inventing one.
        """
        delay = self._policy.base_delay_seconds * 2 ** (self._attempt - 1)
        if not self._may_retry(reason=reason, work_done=work_done, delay=delay):
            return False
        await self._clock.sleep(delay)
        self._attempt += 1
        return True

    def _may_retry(self, *, reason: str | None, work_done: bool, delay: float) -> bool:
        """Whether another attempt is both allowed and affordable."""
        if work_done:
            # Not a launch that never started, so re-running the whole prompt
            # would redo whatever it already did. See `agent_attempts`.
            return False
        if self._attempt >= self._policy.max_attempts:
            return False
        if not _upstream_was_busy(reason):
            return False
        # The backoff is spent from the same deadline, so an attempt is only
        # affordable if paying for the wait still leaves it room to run.
        return self.seconds_left - delay >= _MIN_USEFUL_ATTEMPT_SECONDS


@dataclass(frozen=True)
class UpstreamRetryPolicy:
    """How many times a phase may re-attempt a busy upstream, and when.

    Asked once, before the first attempt, for a `PhaseAttempts`; that object is
    what the caller consults from then on. The caller learns nothing about which
    failures qualify, how many attempts remain, how long the wait is or how the
    deadline is kept - change any of that here and no caller changes.
    """

    #: Total attempts for one phase, the first one included. Bounded, and
    #: small: capacity that has not returned after two backoffs is not the
    #: blip this exists for, and the phases downstream have their own budget.
    max_attempts: int = 3
    #: Doubles per attempt: 5s, then 10s. Long enough for a queue to drain,
    #: short enough that a phase measured in minutes does not notice.
    base_delay_seconds: float = 5.0
    #: How the deadline is read and the backoff served. Swapped for a fake in
    #: tests, which is the only way to assert a 3600-second budget in
    #: milliseconds.
    clock: AttemptClock = AttemptClock()

    def begin(self, *, timeout_seconds: float) -> PhaseAttempts:
        """Start this phase's clock. Call once, before the first attempt.

        ``timeout_seconds`` is the phase's whole budget, and every attempt and
        backoff that follows comes out of it.
        """
        return PhaseAttempts(policy=self, timeout_seconds=timeout_seconds, clock=self.clock)
