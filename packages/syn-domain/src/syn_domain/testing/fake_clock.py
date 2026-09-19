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

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        """Spend ``seconds`` on something other than waiting - an attempt running."""
        self.now += seconds

    def as_attempt_clock(self) -> AttemptClock:
        """This clock, in the shape `UpstreamRetryPolicy` takes."""
        return AttemptClock(monotonic=self.monotonic, sleep=self.sleep)
