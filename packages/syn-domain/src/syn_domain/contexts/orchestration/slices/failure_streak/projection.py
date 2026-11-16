"""How many times in a row each workflow template has failed (#1569).

Read-only. This projection measures the streak; it pauses, refuses and emits
nothing. Keyed by workflow_id, one ``FailureStreak`` per template.

THE RULES, from ``FailureClassification``'s meaning:

- ``platform`` EXTENDS the streak: the machinery failed, which is exactly what
  re-dispatching the template keeps paying for.
- ``unclassified`` EXTENDS it: nobody could say the system worked, and an
  unknown failure is not evidence the template is healthy. Failures recorded
  before #1357 replay as this, so history counts too.
- ``task``, ``correct_refusal`` and ``gate`` are NEUTRAL: each is a positive
  claim that the platform ran the work correctly and the answer was no, which
  says nothing about whether the template is broken.
- WorkflowCompleted RESETS the streak to zero: the template just worked end to
  end, so the failures before it are no longer consecutive.
- ExecutionCancelled and WorkflowInterrupted are NEUTRAL (not handled): someone
  or something stopped the run before it could succeed or fail, so it is
  evidence neither way.

Replay-safe and idempotent: no side effects, and a re-delivered WorkflowFailed
for an execution already in the streak does not count twice
(``FailureStreak.extended_by``). Cost is not summed: WorkflowFailed carries none
(it is Lane 2 telemetry, in the execution_cost projection).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.slices.failure_streak.streak import (
    FailureStreak,
    WorkflowCompletedRef,
    WorkflowFailedRef,
)

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

EXTENDS_STREAK = frozenset({FailureClassification.PLATFORM, FailureClassification.UNCLASSIFIED})
"""The failure classifications that count toward a streak. See the module docstring."""


class FailureStreakProjection(AutoDispatchProjection):
    """Builds the failure streak read model, one entry per workflow template.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "failure_streak"
    VERSION = 1

    def __init__(self, store: ProjectionStore) -> None:
        self._store = store

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    async def _save(self, streak: FailureStreak) -> None:
        await self._store.save(
            self.PROJECTION_NAME, streak.workflow_id, streak.model_dump(mode="json")
        )

    # === Event handlers ===

    async def on_workflow_failed(self, event_data: WorkflowFailedRef) -> None:
        """A platform or unclassified failure extends its template's streak."""
        event = WorkflowFailedRef.model_validate(event_data)
        if not event.workflow_id or not event.execution_id:
            return
        if event.failure_classification not in EXTENDS_STREAK:
            return
        streak = await self.get_streak(event.workflow_id)
        extended = streak.extended_by(event.execution_id, event.failed_at)
        if extended is not streak:
            await self._save(extended)

    async def on_workflow_completed(self, event_data: WorkflowCompletedRef) -> None:
        """A completed execution resets its template's streak to zero."""
        workflow_id = WorkflowCompletedRef.model_validate(event_data).workflow_id
        if workflow_id:
            await self._save(FailureStreak(workflow_id=workflow_id))

    # === Queries ===

    async def get_streak(self, workflow_id: str) -> FailureStreak:
        """The template's current streak; length 0 if it has none."""
        stored = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if not stored:
            return FailureStreak(workflow_id=workflow_id)
        return FailureStreak.model_validate(stored)

    async def list_streaks(self, min_length: int = 1) -> list[FailureStreak]:
        """Every template whose streak is at least ``min_length``, longest first."""
        streaks = [
            FailureStreak.model_validate(stored)
            for stored in await self._store.get_all(self.PROJECTION_NAME)
        ]
        return sorted(
            (streak for streak in streaks if streak.length >= min_length),
            key=lambda streak: streak.length,
            reverse=True,
        )
