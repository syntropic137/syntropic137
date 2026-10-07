"""Projection: one record per execution, plus an index of the day each ended.

The scorecard is asked about a window of days. Keying the records by execution
and indexing them by the UTC day they ended means a request reads its window's
days and the runs in them, never every execution there has been.

Replay-safe: every handler is a pure fold of the event into stored records.
Merged-PR attribution, which needs GitHub, is deliberately NOT done here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
    ExecutionCancelledEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionRequestedEvent import (
    ExecutionRequestedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import (
    PhaseStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowInterruptedEvent import (
    WorkflowInterruptedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
    WorkspaceProvisionedForPhaseEvent,
)
from syn_domain.contexts.orchestration.slices.scorecard.run_record import (
    DayIndex,
    RunOutcome,
    ScorecardPhase,
    ScorecardRun,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import ProjectionStore

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        FailureClassification,
    )

SCORECARD_RUNS = "scorecard_runs"
SCORECARD_DAYS = "scorecard_days"
OPEN_RUNS_KEY = "open"
"""The day-index key holding executions that have started and not ended."""


def _utc(moment: datetime) -> datetime:
    """A naive event timestamp is UTC, as every producer writes it."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def day_key(moment: datetime) -> str:
    """The UTC day a moment falls on, as the day index keys it."""
    return moment.astimezone(UTC).date().isoformat()


class ScorecardProjection(AutoDispatchProjection):
    """Builds the scorecard's per-execution records from orchestration events."""

    PROJECTION_NAME = SCORECARD_RUNS
    VERSION = 3  # Bumped: phases upsert by id, and a failing phase keeps its session

    def __init__(self, store: ProjectionStore) -> None:
        self._store = store

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    async def clear_all_data(self) -> None:
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(SCORECARD_RUNS)
            await self._store.delete_all(SCORECARD_DAYS)

    # === Reads ===

    async def get_run(self, execution_id: str) -> ScorecardRun | None:
        stored = await self._store.get(SCORECARD_RUNS, execution_id)
        return ScorecardRun.model_validate(stored) if stored else None

    async def runs_for_days(self, days: Sequence[str]) -> list[ScorecardRun]:
        """Every execution that ended on one of ``days``, plus those still running."""
        ids: list[str] = []
        for key in (*days, OPEN_RUNS_KEY):
            ids.extend((await self._index(key)).execution_ids)
        runs = [await self.get_run(execution_id) for execution_id in dict.fromkeys(ids)]
        return [run for run in runs if run is not None]

    # === Helpers ===

    async def _index(self, key: str) -> DayIndex:
        stored = await self._store.get(SCORECARD_DAYS, key)
        return DayIndex.model_validate(stored) if stored else DayIndex()

    async def _index_add(self, key: str, execution_id: str) -> None:
        index = await self._index(key)
        if execution_id not in index.execution_ids:
            updated = DayIndex(execution_ids=(*index.execution_ids, execution_id))
            await self._store.save(SCORECARD_DAYS, key, updated.model_dump(mode="json"))

    async def _index_remove(self, key: str, execution_id: str) -> None:
        index = await self._index(key)
        if execution_id in index.execution_ids:
            kept = tuple(i for i in index.execution_ids if i != execution_id)
            await self._store.save(
                SCORECARD_DAYS, key, DayIndex(execution_ids=kept).model_dump(mode="json")
            )

    async def _load(self, execution_id: str) -> ScorecardRun:
        return await self.get_run(execution_id) or ScorecardRun(
            execution_id=execution_id, chain=(execution_id,)
        )

    async def _save(self, run: ScorecardRun) -> None:
        await self._store.save(SCORECARD_RUNS, run.execution_id, run.model_dump(mode="json"))

    async def _end(
        self,
        execution_id: str,
        *,
        outcome: RunOutcome,
        ended_at: datetime,
        failure_classification: FailureClassification | None = None,
    ) -> None:
        run = await self._load(execution_id)
        # First terminal event wins (an interrupt is followed by its cancel),
        # but the indexes are reconciled from the stored end every time: the
        # three writes below are separate, so a redelivery after a partial
        # write is what repairs it.
        if run.outcome is RunOutcome.RUNNING:
            run = run.model_copy(
                update={
                    "outcome": outcome,
                    "ended_at": _utc(ended_at),
                    "failure_classification": failure_classification,
                }
            )
            await self._save(run)
        end = run.ended_at or _utc(ended_at)
        await self._index_add(day_key(end), execution_id)
        await self._index_remove(OPEN_RUNS_KEY, execution_id)

    # === Handlers ===
    # The dispatcher hands each handler ``event.model_dump()``; validating it
    # back into its event class is what makes every field below a declared one.

    async def on_execution_requested(self, event_data: ExecutionRequestedEvent) -> None:
        event = ExecutionRequestedEvent.model_validate(event_data)
        run = await self._load(event.execution_id)
        await self._save(run.model_copy(update={"requested_at": _utc(event.requested_at)}))

    async def on_workflow_execution_started(
        self, event_data: WorkflowExecutionStartedEvent
    ) -> None:
        event = WorkflowExecutionStartedEvent.model_validate(event_data)
        chain: tuple[str, ...] = (event.execution_id,)
        if event.resumed_from is not None:
            parent = await self._load(event.resumed_from.parent_execution_id)
            chain = (*parent.chain, event.execution_id)
            await self._save(parent.model_copy(update={"superseded_by": event.execution_id}))
        run = await self._load(event.execution_id)
        await self._save(
            run.model_copy(
                update={
                    "workflow_id": event.workflow_id,
                    "workflow_name": event.workflow_name,
                    "started_at": _utc(event.started_at),
                    "chain": chain,
                }
            )
        )
        await self._index_add(OPEN_RUNS_KEY, event.execution_id)

    async def on_phase_completed(self, event_data: PhaseCompletedEvent) -> None:
        event = PhaseCompletedEvent.model_validate(event_data)
        run = await self._load(event.execution_id)
        phase = ScorecardPhase(
            phase_id=event.phase_id,
            session_id=event.session_id or run.session_of(event.phase_id),
            success=event.success,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            cache_creation_tokens=event.cache_creation_tokens,
            cache_read_tokens=event.cache_read_tokens,
            total_tokens=event.total_tokens,
            duration_seconds=event.duration_seconds,
        )
        await self._save(run.with_phase(phase))

    async def _record_session(self, execution_id: str, phase_id: str, session_id: str) -> None:
        run = await self._load(execution_id)
        if run.session_of(phase_id) != session_id:
            await self._save(run.with_session(phase_id, session_id))

    async def on_workspace_provisioned_for_phase(
        self, event_data: WorkspaceProvisionedForPhaseEvent
    ) -> None:
        event = WorkspaceProvisionedForPhaseEvent.model_validate(event_data)
        await self._record_session(event.execution_id, event.phase_id, event.session_id)

    async def on_phase_started(self, event_data: PhaseStartedEvent) -> None:
        event = PhaseStartedEvent.model_validate(event_data)
        if event.session_id:
            await self._record_session(event.execution_id, event.phase_id, event.session_id)

    async def on_agent_execution_completed(self, event_data: AgentExecutionCompletedEvent) -> None:
        event = AgentExecutionCompletedEvent.model_validate(event_data)
        if event.session_id:
            await self._record_session(event.execution_id, event.phase_id, event.session_id)
        model = event.agent_model
        if not model:
            return  # written before PC-83: no observed model, never a guessed one
        run = await self._load(event.execution_id)
        if model not in run.models:
            await self._save(run.model_copy(update={"models": (*run.models, model)}))

    async def on_workflow_completed(self, event_data: WorkflowCompletedEvent) -> None:
        event = WorkflowCompletedEvent.model_validate(event_data)
        await self._end(
            event.execution_id, outcome=RunOutcome.COMPLETED, ended_at=event.completed_at
        )

    async def on_workflow_failed(self, event_data: WorkflowFailedEvent) -> None:
        event = WorkflowFailedEvent.model_validate(event_data)
        await self._record_failed_phase(event)
        await self._end(
            event.execution_id,
            outcome=RunOutcome.FAILED,
            ended_at=event.failed_at,
            failure_classification=event.failure_classification,
        )

    async def _record_failed_phase(self, event: WorkflowFailedEvent) -> None:
        """Record the phase the run failed in, from the failure itself.

        A failing phase never emits PhaseCompleted: its spend is only on
        WorkflowFailed's ``failed_phase_*`` fields. Without this, every failed
        verify would drop out of the phase table and the median verify tokens
        target would be read from the verifies that passed.
        """
        if not event.failed_phase_id:
            return
        run = await self._load(event.execution_id)
        if run.outcome is not RunOutcome.RUNNING:
            return  # a second terminal event must not overwrite the first failure's phase
        usage = (
            event.failed_phase_input_tokens,
            event.failed_phase_output_tokens,
            event.failed_phase_cache_creation_tokens,
            event.failed_phase_cache_read_tokens,
        )
        phase = ScorecardPhase(
            phase_id=event.failed_phase_id,
            session_id=run.session_of(event.failed_phase_id),
            success=False,
            input_tokens=usage[0],
            output_tokens=usage[1],
            cache_creation_tokens=usage[2],
            cache_read_tokens=usage[3],
            total_tokens=sum(usage),
            duration_seconds=event.failed_phase_duration_seconds or 0.0,
        )
        await self._save(run.with_phase(phase))

    async def on_execution_cancelled(self, event_data: ExecutionCancelledEvent) -> None:
        event = ExecutionCancelledEvent.model_validate(event_data)
        await self._end(
            event.execution_id, outcome=RunOutcome.CANCELLED, ended_at=event.cancelled_at
        )

    async def on_workflow_interrupted(self, event_data: WorkflowInterruptedEvent) -> None:
        event = WorkflowInterruptedEvent.model_validate(event_data)
        await self._end(
            event.execution_id, outcome=RunOutcome.CANCELLED, ended_at=event.interrupted_at
        )
