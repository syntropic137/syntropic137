"""Projection for per-phase metrics aggregated by workflow.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
Keyed by workflow_id; accumulates token/cost/duration per phase_id.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from event_sourcing import (
    CheckpointedProjection,
    EventEnvelope,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

# Event types this projection subscribes to
_SUBSCRIBED_EVENTS = {
    "PhaseStarted",
    "PhaseCompleted",
}


class WorkflowPhaseMetricsProjection(CheckpointedProjection):
    """Builds per-phase metrics read model from events.

    Stores a pre-aggregated view of token/cost/duration metrics keyed by
    workflow_id so that /api/metrics?workflow_id=<id> is an O(1) read.

    Implements CheckpointedProjection for per-projection position tracking.
    """

    PROJECTION_NAME = "workflow_phase_metrics"
    VERSION = 1

    def __init__(self, store: Any) -> None:
        self._store = store

    # === CheckpointedProjection required methods ===

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return _SUBSCRIBED_EVENTS

    async def handle_event(
        self,
        envelope: EventEnvelope[Any],
        checkpoint_store: ProjectionCheckpointStore,
    ) -> ProjectionResult:
        """Handle an event and save checkpoint atomically."""
        event_type = envelope.event.event_type
        event_data = envelope.event.model_dump()
        global_nonce = envelope.metadata.global_nonce or 0

        try:
            if event_type == "PhaseStarted":
                await self.on_phase_started(event_data)
            elif event_type == "PhaseCompleted":
                await self.on_phase_completed(event_data)

            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=global_nonce,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS

        except Exception:
            return ProjectionResult.FAILURE

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    @property
    def name(self) -> str:
        return self.PROJECTION_NAME

    # === Private helpers ===

    async def _get_workflow_data(self, workflow_id: str) -> dict:
        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            return existing
        return {"phases": {}}

    async def _save_workflow_data(self, workflow_id: str, data: dict) -> None:
        await self._store.save(self.PROJECTION_NAME, workflow_id, data)

    # === Event handlers ===

    async def on_phase_started(self, event_data: dict) -> None:
        """Record phase_name for the (workflow_id, phase_id) pair."""
        workflow_id = event_data.get("workflow_id", "")
        phase_id = event_data.get("phase_id", "")
        if not workflow_id or not phase_id:
            return

        data = await self._get_workflow_data(workflow_id)
        phases = data.setdefault("phases", {})

        if phase_id not in phases:
            phases[phase_id] = {
                "phase_name": event_data.get("phase_name", phase_id),
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": "0",
                "duration_seconds": 0.0,
                "artifact_count": 0,
                "status": "running",
            }
        else:
            # Phase name may not have been set on first encounter
            if not phases[phase_id].get("phase_name"):
                phases[phase_id]["phase_name"] = event_data.get("phase_name", phase_id)

        await self._save_workflow_data(workflow_id, data)

    async def on_phase_completed(self, event_data: dict) -> None:
        """Accumulate token/cost/duration metrics for the phase."""
        workflow_id = event_data.get("workflow_id", "")
        phase_id = event_data.get("phase_id", "")
        if not workflow_id or not phase_id:
            return

        data = await self._get_workflow_data(workflow_id)
        phases = data.setdefault("phases", {})

        if phase_id not in phases:
            # PhaseStarted may have been missed; create a stub entry
            phases[phase_id] = {
                "phase_name": phase_id,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": "0",
                "duration_seconds": 0.0,
                "artifact_count": 0,
                "status": "running",
            }

        entry = phases[phase_id]
        entry["input_tokens"] = entry.get("input_tokens", 0) + event_data.get("input_tokens", 0)
        entry["output_tokens"] = entry.get("output_tokens", 0) + event_data.get("output_tokens", 0)
        entry["total_tokens"] = entry.get("total_tokens", 0) + event_data.get("total_tokens", 0)
        entry["duration_seconds"] = (
            entry.get("duration_seconds", 0.0) + event_data.get("duration_seconds", 0.0)
        )

        existing_cost = Decimal(str(entry.get("cost_usd", "0")))
        phase_cost = Decimal(str(event_data.get("cost_usd", "0")))
        entry["cost_usd"] = str(existing_cost + phase_cost)

        if event_data.get("artifact_id"):
            entry["artifact_count"] = entry.get("artifact_count", 0) + 1

        entry["status"] = "completed" if event_data.get("success", True) else "failed"

        await self._save_workflow_data(workflow_id, data)

    # === Query ===

    async def get_phase_metrics(self, workflow_id: str) -> dict:
        """Return the phases dict for the given workflow_id.

        Returns a dict keyed by phase_id, each value being a metrics dict.
        Returns an empty dict if no data found.
        """
        data = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if data:
            return data.get("phases", {})
        return {}
