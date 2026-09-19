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

#: The smallest timeout that still MEANS a timeout downstream. The workspace
#: provider reads a falsey one as no bound at all -
#: `if not timeout_seconds: return False` in `providers/base.py` - so a
#: remaining budget that truncates to `0` would not produce a short attempt,
#: it would produce an UNBOUNDED one, which is strictly worse than the
#: overrun it came from. No RETRY is ever dispatched this close to its
#: deadline (`_MIN_USEFUL_ATTEMPT_SECONDS` is what stops one being), but the
#: floor is applied where the number is produced regardless: a bound that
#: matters this much should not depend on every caller having got the
#: arithmetic right, and attempt one is dispatched on whatever budget the
#: phase was configured with - see `PhaseAttempts.first_attempt`.
_MIN_MEANINGFUL_TIMEOUT_SECONDS: int = 1


def _upstream_was_busy(reason: str | None) -> bool:
    """Whether ``reason`` is, in full, the upstream reporting its own capacity."""
    return reason in _BUSY_UPSTREAM_REASONS


@dataclass(frozen=True)
class AttemptGrant:
    """Permission to dispatch ONE attempt, and the timeout it must be given.

    THE TWO TRAVEL TOGETHER BECAUSE THE DEFECT WAS THEM TRAVELLING SEPARATELY.
    The decision to go again used to be taken against one reading of the clock
    and the timeout computed from a later one, at the dispatch line. Between
    the two readings the clock keeps running, so a deadline that expired in
    between produced an attempt nobody had approved, bounded by a number
    nobody had checked: `int(seconds_left)` past the deadline is `0`, and the
    workspace provider reads a falsey timeout as NO timeout at all. The
    attempt that should not have run became the one attempt with no bound.

    So the budget is read ONCE and both the approval and the number come out
    of that single reading. A caller holding one of these is holding a
    timeout that was affordable when it was granted, and cannot re-derive a
    different one: there is no arithmetic left for it to get wrong.
    """

    #: Whole seconds to hand the handler. Never zero, never negative, and for
    #: a successor never below `_MIN_USEFUL_ATTEMPT_SECONDS`.
    timeout_seconds: int


def _meaningful_timeout(remaining: float) -> int:
    """``remaining`` as whole seconds the handler can be given, never falsey."""
    return max(int(remaining), _MIN_MEANINGFUL_TIMEOUT_SECONDS)


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
    after each failure. `first_attempt` grants the attempt that always runs;
    `wait_before_retry` grants or refuses every one after it. Both hand back
    an `AttemptGrant`, which is the only place a dispatch timeout comes from -
    `seconds_left` is the budget, not a number to dispatch on.

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

    def first_attempt(self) -> AttemptGrant:
        """The grant for attempt one, which is never refused.

        DELIBERATELY NOT SUBJECT TO `_MIN_USEFUL_ATTEMPT_SECONDS`. That
        minimum asks "is there enough LEFT of a budget already partly spent to
        be worth starting another attempt in", and it can only be asked once
        something has been spent. Nothing has been, here: this is the phase
        running at all, on exactly the budget an operator configured for it,
        and that number is not this module's to veto. A phase declaring
        `timeout_seconds: 10` gets its ten seconds - refusing it would fail
        the phase without ever dispatching it, and `run_phase_agent` would
        have no agent result to report the failure WITH, so the refusal could
        only surface as a crash where a short run used to be.

        What does apply is the floor that keeps the number meaningful: a
        timeout of zero is not a short attempt downstream, it is an unbounded
        one.
        """
        return AttemptGrant(timeout_seconds=_meaningful_timeout(self.seconds_left))

    @property
    def attempt(self) -> int:
        """Which attempt is running, 1-based. For logging, not for deciding."""
        return self._attempt

    @property
    def max_attempts(self) -> int:
        """The bound this phase was started under. For logging, not for deciding."""
        return self._policy.max_attempts

    async def wait_before_retry(
        self, *, reason: str | None, work_done: bool
    ) -> AttemptGrant | None:
        """Sleep out the backoff and grant the failed attempt a successor, or refuse it.

        ``reason`` is what the attempt that just failed reported; ``work_done``
        is whether that attempt (or any before it) had already got somewhere -
        see `agent_attempts`.

        `None` means this failure is final and the caller must report ``reason``
        as it stands. It says nothing about WHY it is final - a genuine error, a
        spent budget, an expired deadline and an attempt that had already
        started working all end the run the same way, with the same cause, and a
        caller that branched on the difference would be inventing one.

        An `AttemptGrant` is both the answer and the timeout that answer was
        computed against. The caller dispatches with the number it is handed
        and does not read this object's clock again: see `AttemptGrant`.
        """
        delay = self._policy.base_delay_seconds * 2 ** (self._attempt - 1)
        if not self._may_retry(reason=reason, work_done=work_done, delay=delay):
            return None
        await self._clock.sleep(delay)
        # ASKED AGAIN, because the check above was a forecast and this is the
        # outcome. `sleep(delay)` does not promise to return after `delay`: the
        # host can suspend, the scheduler can run long, and the loop can be
        # busy. Whatever the cause, the deadline is read from the clock and the
        # clock has moved. Before this second check the answer was already
        # committed to - the caller was told to go again and handed whatever
        # `seconds_left` had become, which on an overshoot is 0, which the
        # provider reads as NO TIMEOUT. So an oversleep did not merely waste
        # the budget, it removed the bound the budget existed to impose.
        #
        # READ ONCE, and used for both halves. Asking `seconds_left` here and
        # letting the caller ask again at the dispatch line put a second,
        # unchecked reading between the approval and the attempt: the clock
        # moves in that gap too, so a budget that passed this check at 30s
        # could be dispatched at 0s, floored to a meaningless 1s, and the
        # recheck above would have prevented nothing. The grant closes the gap
        # by carrying the checked number with the decision.
        remaining = self.seconds_left
        if not self._affords_an_attempt(remaining):
            return None
        self._attempt += 1
        return AttemptGrant(timeout_seconds=_meaningful_timeout(remaining))

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
        return self._affords_an_attempt(self.seconds_left - delay)

    def _affords_an_attempt(self, remaining: float) -> bool:
        """Whether ``remaining`` seconds still buy an attempt worth starting.

        One rule, applied twice: `_may_retry` passes what the budget WILL be
        once the backoff is paid for, and `wait_before_retry` passes what it
        turned out to BE. Written once so the forecast and the outcome cannot
        drift into disagreeing about what "affordable" means, and taking the
        budget as an argument rather than reading it so the caller decides
        which reading is being judged - the reading that is judged is then the
        one that denominates the grant.
        """
        return remaining >= _MIN_USEFUL_ATTEMPT_SECONDS


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
