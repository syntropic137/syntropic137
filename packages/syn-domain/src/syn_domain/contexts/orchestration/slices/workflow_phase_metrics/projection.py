"""Projection for per-phase metrics aggregated by workflow.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
Keyed by workflow_id; accumulates token/duration metrics per phase_id.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from event_sourcing import ProjectionStore

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.slices.workflow_phase_metrics.phase_entry import (
    PhaseMetricsEntry,
)


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
    VERSION = 4  # Bumped: phases now store started_at, so a running phase can be timed

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

    # === Event handlers ===

    async def on_phase_started(self, event_data: dict) -> None:
        """Open a run of this phase: it is running, and it started just now.

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
            entry,
            # Phase name may not have been set on first encounter
            phase_name=entry.phase_name or phase_name,
            status="running",
            started_at=event_data.get("started_at"),
        )

        await self._save_phases(workflow_id, phases)

    async def on_phase_completed(self, event_data: dict) -> None:
        """Accumulate token/duration metrics for the phase."""
        workflow_id = event_data.get("workflow_id", "")
        phase_id = event_data.get("phase_id", "")
        if not workflow_id or not phase_id:
            return

        phases = await self._load_phases(workflow_id)
        # PhaseStarted may have been missed; fall back to a fresh entry
        entry = phases.get(phase_id) or PhaseMetricsEntry(phase_id=phase_id, phase_name=phase_id)

        phases[phase_id] = replace(
            entry.with_finished_run(event_data.get("duration_seconds")),
            input_tokens=entry.input_tokens + event_data.get("input_tokens", 0),
            output_tokens=entry.output_tokens + event_data.get("output_tokens", 0),
            total_tokens=entry.total_tokens + event_data.get("total_tokens", 0),
            artifact_count=entry.artifact_count + (1 if event_data.get("artifact_id") else 0),
            status="completed" if event_data.get("success", True) else "failed",
        )

        await self._save_phases(workflow_id, phases)

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Mark the failed phase's real status and duration.

        A failed phase never gets a PhaseCompleted event -- the only other
        writer of these fields -- so without this it stays "running" and keeps
        accruing wall-clock time against a run that ended, forever (#1036).
        """
        workflow_id = event_data.get("workflow_id", "")
        phase_id = event_data.get("failed_phase_id")
        if not workflow_id or not phase_id:
            return

        phases = await self._load_phases(workflow_id)
        entry = phases.get(phase_id)
        if entry is None:
            return

        failed_run = entry.with_finished_run(event_data.get("failed_phase_duration_seconds"))
        phases[phase_id] = replace(failed_run, status="failed")

        await self._save_phases(workflow_id, phases)

    # === Query ===

    async def get_phase_metrics(self, workflow_id: str) -> dict[str, PhaseMetricsEntry]:
        """Return this workflow's phases, keyed by phase_id.

        Entries are typed so that no caller has to know which stored field
        means what -- in particular, how a settled total and a run still in
        flight combine into "how long has this phase run". Empty if no data
        found.
        """
        return await self._load_phases(workflow_id)
