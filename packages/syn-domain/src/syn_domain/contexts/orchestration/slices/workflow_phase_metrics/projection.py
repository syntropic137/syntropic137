"""Projection for per-phase metrics aggregated by workflow.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
Keyed by workflow_id; accumulates token/duration metrics per phase_id, with
the runs still in flight tracked per execution_id underneath.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from event_sourcing import ProjectionStore

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.slices.workflow_phase_metrics.phase_entry import (
    PhaseMetricsEntry,
)

NO_EXECUTION = ""
"""The run key for an event that carried no execution id.

PhaseStarted, PhaseCompleted, WorkflowFailed, ExecutionCancelled and
WorkflowInterrupted all require one, so this is only reached by a truncated or
hand-built payload. Such runs share a single slot, which is exactly how this
projection behaved before it could tell executions apart: a degraded answer for
a degraded input, rather than a branch every reader has to carry.
"""


def _execution_of(event_data: dict) -> str:
    """Which execution's run of a phase this event is about."""
    return event_data.get("execution_id") or NO_EXECUTION


class WorkflowPhaseMetricsProjection(AutoDispatchProjection):
    """Builds per-phase metrics read model from events.

    Stores a pre-aggregated view of token/duration metrics keyed by
    workflow_id so that /api/metrics?workflow_id=<id> is an O(1) read.

    Every handler loads typed entries, folds the event into them and writes
    them back, so the stored shape is described in exactly one place
    (``PhaseMetricsEntry``) rather than at each read and write of it.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "workflow_phase_metrics"
    VERSION = 5  # Bumped: phases track their in-flight runs per execution_id

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

    # === Private helpers ===

    async def _load_phases(self, workflow_id: str) -> dict[str, PhaseMetricsEntry]:
        data = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if not data:
            return {}
        return {
            phase_id: PhaseMetricsEntry.from_stored(phase_id, stored)
            for phase_id, stored in data.get("phases", {}).items()
        }

    async def _save_phases(self, workflow_id: str, phases: Mapping[str, PhaseMetricsEntry]) -> None:
        await self._store.save(
            self.PROJECTION_NAME,
            workflow_id,
            {"phases": {phase_id: entry.to_stored() for phase_id, entry in phases.items()}},
        )

    async def _close_execution(
        self,
        event_data: dict,
        *,
        status: str,
        ended_at: datetime | str | None,
        recorded_seconds: float | None = None,
    ) -> None:
        """Close whatever run this execution still had open, however it ended.

        An execution that has stopped is not running any phase, so its run has
        to be closed by every route out - completion, failure, cancellation,
        interruption. Leaving one open would keep the workflow's phase
        reporting "running" and accruing wall-clock time against a run that is
        over, forever (#1036) - and now, since runs no longer overwrite each
        other, no later execution would come along and paper over it.

        An execution runs its phases one at a time, so at most one run of one
        phase is open per execution; the loop is over the workflow's phases to
        find it, not because several can be open at once.
        """
        workflow_id = event_data.get("workflow_id", "")
        if not workflow_id:
            return
        execution_id = _execution_of(event_data)

        phases = await self._load_phases(workflow_id)
        open_phase_ids = [
            phase_id for phase_id, entry in phases.items() if execution_id in entry.active_runs
        ]
        if not open_phase_ids:
            return

        for phase_id in open_phase_ids:
            phases[phase_id] = phases[phase_id].with_run_finished(
                execution_id,
                status=status,
                recorded_seconds=recorded_seconds,
                ended_at=ended_at,
            )

        await self._save_phases(workflow_id, phases)

    # === Event handlers ===

    async def on_phase_started(self, event_data: dict) -> None:
        """Open this execution's run of the phase: it is running, from now.

        Both facts are recorded on every start, not only the first. The same
        phase runs again on every execution of its workflow (this projection
        is keyed by workflow_id), and an entry left saying "completed, 10s"
        while the phase is running again cannot report that it is running, let
        alone how long for. The accumulated totals beside them are untouched -
        a new run adds to the workflow's history, it does not replace it.
        """
        workflow_id = event_data.get("workflow_id", "")
        phase_id = event_data.get("phase_id", "")
        if not workflow_id or not phase_id:
            return

        phases = await self._load_phases(workflow_id)
        phase_name = event_data.get("phase_name") or phase_id
        entry = phases.get(phase_id) or PhaseMetricsEntry(phase_id=phase_id, phase_name=phase_name)

        phases[phase_id] = replace(
            entry.with_run_started(_execution_of(event_data), event_data.get("started_at")),
            # Phase name may not have been set on first encounter
            phase_name=entry.phase_name or phase_name,
        )

        await self._save_phases(workflow_id, phases)

    async def on_phase_completed(self, event_data: dict) -> None:
        """Accumulate token/duration metrics for the phase.

        Only the completing execution's run is closed. Any other execution of
        this workflow still in this phase keeps its run, and the phase keeps
        reporting itself as running for as long as one of them is.
        """
        workflow_id = event_data.get("workflow_id", "")
        phase_id = event_data.get("phase_id", "")
        if not workflow_id or not phase_id:
            return

        phases = await self._load_phases(workflow_id)
        # PhaseStarted may have been missed; fall back to a fresh entry
        entry = phases.get(phase_id) or PhaseMetricsEntry(phase_id=phase_id, phase_name=phase_id)

        finished = entry.with_run_finished(
            _execution_of(event_data),
            status="completed" if event_data.get("success", True) else "failed",
            recorded_seconds=event_data.get("duration_seconds"),
            ended_at=event_data.get("completed_at"),
        )
        phases[phase_id] = replace(
            finished,
            input_tokens=entry.input_tokens + event_data.get("input_tokens", 0),
            output_tokens=entry.output_tokens + event_data.get("output_tokens", 0),
            total_tokens=entry.total_tokens + event_data.get("total_tokens", 0),
            artifact_count=entry.artifact_count + (1 if event_data.get("artifact_id") else 0),
        )

        await self._save_phases(workflow_id, phases)

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Mark the failed run's real status and duration.

        A failed phase never gets a PhaseCompleted event -- the only other
        writer of these fields -- so without this it stays "running" and keeps
        accruing wall-clock time against a run that ended, forever (#1036).

        ``failed_phase_duration_seconds`` is how long the run had been going
        when the failure was caught; the processor measured it, so it beats
        anything derived from ``failed_at`` here.
        """
        await self._close_execution(
            event_data,
            status="failed",
            ended_at=event_data.get("failed_at"),
            recorded_seconds=event_data.get("failed_phase_duration_seconds"),
        )

    async def on_execution_cancelled(self, event_data: dict) -> None:
        """A cancelled execution's run ended when the cancellation landed.

        Nothing records how long it had run, so the elapsed time is measured
        against ``cancelled_at`` -- NOT the wall clock, which would keep the
        phase's total growing forever after the run stopped.
        """
        await self._close_execution(
            event_data, status="cancelled", ended_at=event_data.get("cancelled_at")
        )

    async def on_workflow_interrupted(self, event_data: dict) -> None:
        """Same as cancellation, by the forceful route (SIGINT mid-stream)."""
        await self._close_execution(
            event_data, status="interrupted", ended_at=event_data.get("interrupted_at")
        )

    # === Query ===

    async def get_phase_metrics(self, workflow_id: str) -> dict[str, PhaseMetricsEntry]:
        """Return this workflow's phases, keyed by phase_id.

        Entries are typed so that no caller has to know which stored field
        means what -- in particular, how a settled total and the runs still in
        flight combine into "how long has this phase run". Empty if no data
        found.
        """
        return await self._load_phases(workflow_id)
