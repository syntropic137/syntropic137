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
from pydantic import TypeAdapter

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
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

SCORECARD_RUNS = "scorecard_runs"
SCORECARD_DAYS = "scorecard_days"
OPEN_RUNS_KEY = "open"
"""The day-index key holding executions that have started and not ended."""

_DATETIME = TypeAdapter(datetime)


def _as_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = _DATETIME.validate_python(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def day_key(moment: datetime) -> str:
    """The UTC day a moment falls on, as the day index keys it."""
    return moment.astimezone(UTC).date().isoformat()


class ScorecardProjection(AutoDispatchProjection):
    """Builds the scorecard's per-execution records from orchestration events."""

    PROJECTION_NAME = SCORECARD_RUNS
    VERSION = 2  # Bumped: a failing phase's tokens are recorded from WorkflowFailed

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
        event_data: dict,
        *,
        outcome: RunOutcome,
        ended_at: object,
        failure_classification: FailureClassification | None = None,
    ) -> None:
        execution_id = event_data.get("execution_id") or ""
        if not execution_id:
            return
        run = await self._load(execution_id)
        if run.outcome is not RunOutcome.RUNNING:
            return  # first terminal event wins: an interrupt is followed by its cancel
        end = _as_datetime(ended_at) or run.started_at
        run = run.model_copy(
            update={
                "outcome": outcome,
                "ended_at": end,
                "failure_classification": failure_classification,
            }
        )
        await self._save(run)
        await self._index_remove(OPEN_RUNS_KEY, execution_id)
        if end is not None:
            await self._index_add(day_key(end), execution_id)

    # === Handlers ===

    async def on_execution_requested(self, event_data: dict) -> None:
        execution_id = event_data.get("execution_id") or ""
        if not execution_id:
            return
        run = await self._load(execution_id)
        await self._save(
            run.model_copy(update={"requested_at": _as_datetime(event_data.get("requested_at"))})
        )

    async def on_workflow_execution_started(self, event_data: dict) -> None:
        execution_id = event_data.get("execution_id") or ""
        if not execution_id:
            return
        chain: tuple[str, ...] = (execution_id,)
        resumed_from = event_data.get("resumed_from") or {}
        parent_id = resumed_from.get("parent_execution_id") if resumed_from else None
        if parent_id:
            parent = await self._load(parent_id)
            chain = (*parent.chain, execution_id)
            await self._save(parent.model_copy(update={"superseded_by": execution_id}))
        run = await self._load(execution_id)
        await self._save(
            run.model_copy(
                update={
                    "workflow_id": event_data.get("workflow_id") or "",
                    "workflow_name": event_data.get("workflow_name") or "",
                    "started_at": _as_datetime(event_data.get("started_at")),
                    "chain": chain,
                }
            )
        )
        await self._index_add(OPEN_RUNS_KEY, execution_id)

    async def on_phase_completed(self, event_data: dict) -> None:
        execution_id = event_data.get("execution_id") or ""
        if not execution_id:
            return
        run = await self._load(execution_id)
        phase = ScorecardPhase(
            phase_id=event_data.get("phase_id") or "",
            session_id=event_data.get("session_id"),
            success=bool(event_data.get("success")),
            input_tokens=event_data.get("input_tokens") or 0,
            output_tokens=event_data.get("output_tokens") or 0,
            cache_creation_tokens=event_data.get("cache_creation_tokens") or 0,
            cache_read_tokens=event_data.get("cache_read_tokens") or 0,
            total_tokens=event_data.get("total_tokens") or 0,
            duration_seconds=event_data.get("duration_seconds") or 0.0,
        )
        await self._save(run.model_copy(update={"phases": (*run.phases, phase)}))

    async def on_agent_execution_completed(self, event_data: dict) -> None:
        execution_id = event_data.get("execution_id") or ""
        model = event_data.get("agent_model")
        if not execution_id or not model:
            return
        run = await self._load(execution_id)
        if model not in run.models:
            await self._save(run.model_copy(update={"models": (*run.models, model)}))

    async def on_workflow_completed(self, event_data: dict) -> None:
        await self._end(
            event_data, outcome=RunOutcome.COMPLETED, ended_at=event_data.get("completed_at")
        )

    async def on_workflow_failed(self, event_data: dict) -> None:
        await self._record_failed_phase(event_data)
        await self._end(
            event_data,
            outcome=RunOutcome.FAILED,
            ended_at=event_data.get("failed_at"),
            failure_classification=FailureClassification(
                event_data.get("failure_classification") or FailureClassification.UNCLASSIFIED
            ),
        )

    async def _record_failed_phase(self, event_data: dict) -> None:
        """Record the phase the run failed in, from the failure itself.

        A failing phase never emits PhaseCompleted: its spend is only on
        WorkflowFailed's ``failed_phase_*`` fields. Without this, every failed
        verify would drop out of the phase table and the median verify tokens
        target would be read from the verifies that passed.
        """
        execution_id = event_data.get("execution_id") or ""
        phase_id = event_data.get("failed_phase_id")
        if not execution_id or not phase_id:
            return
        run = await self._load(execution_id)
        if run.outcome is not RunOutcome.RUNNING:
            return  # replaying a second terminal event must not add the phase twice
        usage = (
            event_data.get("failed_phase_input_tokens") or 0,
            event_data.get("failed_phase_output_tokens") or 0,
            event_data.get("failed_phase_cache_creation_tokens") or 0,
            event_data.get("failed_phase_cache_read_tokens") or 0,
        )
        phase = ScorecardPhase(
            phase_id=phase_id,
            success=False,
            input_tokens=usage[0],
            output_tokens=usage[1],
            cache_creation_tokens=usage[2],
            cache_read_tokens=usage[3],
            total_tokens=sum(usage),
            duration_seconds=event_data.get("failed_phase_duration_seconds") or 0.0,
        )
        await self._save(run.model_copy(update={"phases": (*run.phases, phase)}))

    async def on_execution_cancelled(self, event_data: dict) -> None:
        await self._end(
            event_data, outcome=RunOutcome.CANCELLED, ended_at=event_data.get("cancelled_at")
        )

    async def on_workflow_interrupted(self, event_data: dict) -> None:
        await self._end(
            event_data, outcome=RunOutcome.CANCELLED, ended_at=event_data.get("interrupted_at")
        )
