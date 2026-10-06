"""A phase's cost limit, held against what its agent has spent so far (#1376).

`timeout_seconds` bounds wall-clock time, and a phase that fans out to parallel
subagents turns a time bound into an unbounded cost: exec-d9ec05de3174 spent
USD 77.35 in one phase before its timeout ended it. `max_cost_usd` is the bound
on the other axis.

WHAT IS COUNTED is the per-turn usage the stream already reports, priced by
`price_tokens` - the one pricing entry point, the same one the
`execution_cost` projection prices those observations with. This is Lane 2
telemetry read where it arrives, in-process and per model call, so no second
pricing path and no wait on a projection to catch up.

WHAT IS DECIDED here is only "has this phase spent past its limit". Stopping
the agent is the stream processor's job and recording the failure is the
aggregate's (`PhaseCostLimitExceededError` reaches it through the ordinary
failure path), so telemetry never writes domain state.

ONE PER PHASE, NOT PER ATTEMPT, for the reason the deadline is one per phase
(`agent_attempts.run_phase_agent`): a retried attempt spends from the same
budget, or three attempts would cost three phases' money.

Two limits worth stating rather than discovering:

- The check is post-hoc per turn. Turns already in flight when the limit is
  crossed - parallel subagents especially - still land, so the phase can end
  above its limit by roughly what was in flight. It is not a pre-call
  reservation.
- A turn that cannot be priced (no model, or no rate for it) adds nothing.
  `price_tokens` already logs it as unpriced; guessing a rate would be worse.
"""

from __future__ import annotations

from decimal import Decimal

from syn_shared.pricing import price_tokens


class PhaseCostLimit:
    """Running priced spend of one phase against its `max_cost_usd`."""

    def __init__(self, max_cost_usd: float) -> None:
        self._limit = Decimal(str(max_cost_usd))
        self._spent = Decimal("0")

    @property
    def spent_usd(self) -> Decimal:
        return self._spent

    def record_turn(
        self,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
    ) -> None:
        """Add one model call's usage, priced at the model that call names."""
        priced = price_tokens(model, input_tokens, output_tokens, cache_creation, cache_read)
        if priced.cost is not None:
            self._spent += priced.cost

    def exceeded(self) -> str | None:
        """Why the phase must stop, or None while it is within its limit."""
        if self._spent <= self._limit:
            return None
        return f"cost limit USD {self._limit:.2f} exceeded at USD {self._spent:.2f}"


def spend(
    limit: PhaseCostLimit | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_creation: int = 0,
    cache_read: int = 0,
) -> None:
    """Record a turn against `limit`, if the phase declared one."""
    if limit is not None:
        limit.record_turn(model, input_tokens, output_tokens, cache_creation, cache_read)


def limit_exceeded(limit: PhaseCostLimit | None) -> str | None:
    """Why the phase must stop, or None - always None for a phase with no limit."""
    return limit.exceeded() if limit is not None else None


def raise_if_stopped_on_cost(phase_id: str, reason: str | None) -> None:
    """Turn a cost stop reported by the stream into the phase's failure."""
    if reason is not None:
        raise PhaseCostLimitExceededError(phase_id, reason)


class PhaseCostLimitExceededError(Exception):
    """A phase was stopped because it spent past its `max_cost_usd` (#1376).

    Raised by the processor so the stop reaches the aggregate the way every
    other phase failure does - a failed execution, classified PLATFORM, and so
    resumable exactly like one killed at its `timeout_seconds`. NOT routed as a
    cancel: a cancelled execution refuses resume, and nobody decided this work
    should stop for good, only that it had spent enough in one go.
    """

    def __init__(self, phase_id: str, reason: str) -> None:
        super().__init__(f"Phase {phase_id} stopped: {reason}")
        self.phase_id = phase_id
        self.reason = reason
