"""When a failure streak refuses an automatic dispatch (#1569).

The rule: a trigger may not dispatch a workflow template whose failure streak
has reached the configured threshold. A threshold of 0 turns the rule off.

Only AUTOMATIC (trigger-fired) dispatch is refused. A manual run, started by a
person from the CLI or the API, is never refused here, and that is load-bearing:
a completed execution is the only thing that resets a streak, so refusing every
dispatch would leave the template refused forever. The manual run is the way
out. The caller that applies this rule is the trigger dispatcher, and only it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.failure_streak.streak import FailureStreak

REFUSAL_REASON = "failure_streak"
"""The name a refused dispatch is recorded under, first in its description."""

EXECUTIONS_NAMED = 5
"""How many of the most recent failed execution ids a description names."""


class StreakRefusal(BaseModel):
    """A trigger dispatch refused because its template's failure streak is too long."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str
    length: int
    threshold: int
    execution_ids: tuple[str, ...]

    def describe(self) -> str:
        """The recorded reason: its name, the streak, the threshold, the last executions."""
        last = ", ".join(self.execution_ids[-EXECUTIONS_NAMED:]) or "none kept"
        return (
            f"{REFUSAL_REASON}: workflow {self.workflow_id} has failed {self.length} times"
            f" in a row, at or over the threshold of {self.threshold}"
            f" (last executions: {last}). A manual run that completes resets it."
        )


def should_refuse(streak: FailureStreak, threshold: int) -> StreakRefusal | None:
    """The refusal for an automatic dispatch of ``streak``'s template, or None to dispatch."""
    if threshold <= 0 or streak.length < threshold:
        return None
    return StreakRefusal(
        workflow_id=streak.workflow_id,
        length=streak.length,
        threshold=threshold,
        execution_ids=streak.execution_ids,
    )


class _Streaks(Protocol):
    async def get_streak(self, workflow_id: str) -> FailureStreak: ...


class TriggerDispatchStreakCheck:
    """Applies ``should_refuse`` to a template's current streak, for the trigger dispatcher.

    Never hand this to a manual start path: see the module docstring.
    """

    def __init__(self, streaks: _Streaks, threshold: int) -> None:
        self._streaks = streaks
        self._threshold = threshold

    async def refusal_for(self, workflow_id: str) -> StreakRefusal | None:
        """Why a trigger may not dispatch ``workflow_id`` now, or None if it may."""
        if self._threshold <= 0:
            return None
        return should_refuse(await self._streaks.get_streak(workflow_id), self._threshold)
