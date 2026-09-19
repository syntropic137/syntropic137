"""A clock a test can move, for asserting budgets measured in hours (#1303).

A phase's retry budget is one deadline spanning every attempt and every backoff
between them. Against the real clock the only way to check that a 3600-second
phase stays inside 3600 seconds is to spend 3600 seconds, so the property that
matters most - the one that used to let three attempts run for three hours -
is exactly the one no test could afford to assert.

This makes time a value the test sets. Sleeping advances it, so a backoff costs
the budget here what it costs in production, and an attempt "taking" twenty
minutes is one call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import AttemptClock


@dataclass
class FakeClock:
    """Monotonic time under the test's control, and every sleep served from it."""

    #: Where "now" is. Moves only when something spends time.
    now: float = 0.0
    #: Every backoff served, in order - the schedule, as observed rather than
    #: as configured.
    slept: list[float] = field(default_factory=list)
    #: Extra time every sleep takes beyond what it was asked for.
    #:
    #: `sleep(delay)` does not promise to return after `delay`, and the gap is
    #: not a rounding error: a suspended host, a busy loop or a descheduled
    #: container can come back arbitrarily late. That is a fact about real
    #: clocks that only a fake one can be made to assert, and it is the fact
    #: behind the defect this exists for - an overslept backoff that used to
    #: report the phase still affordable and hand the next attempt a timeout of
    #: zero, which the workspace provider reads as no timeout at all (#1344).
    oversleeps_by: float = 0.0
    #: How far the clock moves between one reading of it and the next.
    #:
    #: A real monotonic clock is never read twice at the same instant: work
    #: happens between the readings, and under a loaded host or a descheduled
    #: container that work can take far longer than the code doing it expects.
    #: A fake that answers every reading with the same number cannot express
    #: that, so it cannot express the defect it hides - a budget CHECKED at one
    #: reading and DISPATCHED on a later one, where the later reading is past
    #: the deadline and truncates to a timeout of zero (#1344). Set this and
    #: every reading costs time, which is what makes "how many times does this
    #: path read the clock, and which reading does the handler get" an
    #: assertable property rather than a code-reading exercise.
    drifts_per_reading: float = 0.0

    def monotonic(self) -> float:
        reading = self.now
        self.now += self.drifts_per_reading
        return reading

    async def sleep(self, seconds: float) -> None:
        # Recorded as ASKED and charged as TAKEN, deliberately: `slept` is the
        # schedule under test and must not silently absorb the overshoot, while
        # `now` is the clock everything else reads and must.
        self.slept.append(seconds)
        self.now += seconds + self.oversleeps_by

    def advance(self, seconds: float) -> None:
        """Spend ``seconds`` on something other than waiting - an attempt running."""
        self.now += seconds

    def as_attempt_clock(self) -> AttemptClock:
        """This clock, in the shape `UpstreamRetryPolicy` takes."""
        return AttemptClock(monotonic=self.monotonic, sleep=self.sleep)
