"""Projection for per-phase metrics aggregated by workflow.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
Keyed by workflow_id; accumulates token/cost/duration per phase_id.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol

from event_sourcing import AutoDispatchProjection


class WorkflowPhaseMetricsProjection(AutoDispatchProjection):
    """Builds per-phase metrics read model from events.

    Stores a pre-aggregated view of token/cost/duration metrics keyed by
    workflow_id so that /api/metrics?workflow_id=<id> is an O(1) read.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "workflow_phase_metrics"
    VERSION = 1

    def __init__(self, store: ProjectionStoreProtocol) -> None:
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
        entry["duration_seconds"] = entry.get("duration_seconds", 0.0) + event_data.get(
            "duration_seconds", 0.0
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
