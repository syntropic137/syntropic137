"""Projection for workflow execution detail view.

This projection maintains detailed execution state including per-phase metrics.
It's updated by WorkflowExecutionStarted, PhaseStarted, PhaseCompleted,
WorkflowCompleted, and WorkflowFailed events.

Uses AutoDispatchProjection (ADR-014) for reliable position tracking.
"""

from decimal import Decimal
from typing import Any

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.phase_detail import (
    PhaseDetail,
)


class WorkflowExecutionDetailProjection(AutoDispatchProjection):
    """Builds workflow execution detail read model from events.

    This projection maintains detailed execution state including:
    - Overall execution status and metrics
    - Per-phase execution details with individual metrics
    - Artifact references

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "workflow_execution_details"
    VERSION = 3  # Bumped: migrated to AutoDispatchProjection, removed dead handlers

    def __init__(self, store: Any):  # Using Any to avoid circular import
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version - increment to trigger rebuild."""
        return self.VERSION

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    @staticmethod
    def _find_phase(
        phases: list[dict[str, Any]], phase_id: str
    ) -> tuple[int, dict[str, Any]] | None:
        """Find a phase by ID, returning (index, phase_dict) or None."""
        for i, p in enumerate(phases):
            if p.get("phase_id") == phase_id:
                return i, p
        return None

    @staticmethod
    def _aggregate_totals(
        detail: dict[str, Any],
        input_tokens: int,
        output_tokens: int,
        duration: float,
        cost: Decimal,
    ) -> None:
        """Add phase metrics to execution totals."""
        detail["total_input_tokens"] = detail.get("total_input_tokens", 0) + input_tokens
        detail["total_output_tokens"] = detail.get("total_output_tokens", 0) + output_tokens
        detail["total_duration_seconds"] = detail.get("total_duration_seconds", 0.0) + duration
        existing_cost = Decimal(str(detail.get("total_cost_usd", "0")))
        detail["total_cost_usd"] = str(existing_cost + cost)

    async def on_workflow_execution_started(self, event_data: dict) -> None:
        """Handle WorkflowExecutionStarted event.

        Creates a new execution detail with pending phases.
        """
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        # Create initial phases from workflow definition (all pending)
        # Note: In a full implementation, we'd get phase names from workflow
        # For now, phases are populated as they start/complete
        detail = {
            "execution_id": execution_id,
            "workflow_id": event_data.get("workflow_id", ""),
            "workflow_name": event_data.get("workflow_name", ""),
            "status": "running",
            "started_at": event_data.get("started_at"),
            "completed_at": None,
            "phases": [],  # Populated as phases start/complete
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": "0",
            "total_duration_seconds": 0.0,
            "artifact_ids": [],
            "error_message": None,
        }
        await self._store.save(self.PROJECTION_NAME, execution_id, detail)

    async def on_phase_started(self, event_data: dict) -> None:
        """Handle PhaseStarted event.

        Adds a new phase entry with 'running' status.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        phase_id = event_data.get("phase_id", "")
        phases = existing.get("phases", [])

        if self._find_phase(phases, phase_id) is None:
            phase = PhaseDetail.running(
                phase_id=phase_id,
                name=event_data.get("phase_name", phase_id),
                session_id=event_data.get("session_id"),
                started_at=event_data.get("started_at"),
            )
            phases.append(phase.to_dict())
            existing["phases"] = phases
            await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    @staticmethod
    def _update_phase_metrics(phase: dict[str, Any], event_data: dict) -> None:
        """Apply completion metrics from event data onto a phase dict."""
        phase["status"] = "completed"
        if event_data.get("session_id"):
            phase["session_id"] = event_data["session_id"]
        phase["artifact_id"] = event_data.get("artifact_id")
        phase["input_tokens"] = event_data.get("input_tokens", 0)
        phase["output_tokens"] = event_data.get("output_tokens", 0)
        phase["cache_creation_tokens"] = event_data.get("cache_creation_tokens", 0)
        phase["cache_read_tokens"] = event_data.get("cache_read_tokens", 0)
        phase["total_tokens"] = event_data.get("total_tokens", 0)
        phase["duration_seconds"] = event_data.get("duration_seconds", 0.0)
        phase["cost_usd"] = str(event_data.get("cost_usd", "0"))
        phase["completed_at"] = event_data.get("completed_at")

    @staticmethod
    def _track_artifact(existing: dict[str, Any], artifact_id: str | None) -> None:
        """Add an artifact ID to the execution detail if not already tracked."""
        if not artifact_id:
            return
        artifact_ids = existing.get("artifact_ids", [])
        if artifact_id not in artifact_ids:
            artifact_ids.append(artifact_id)
        existing["artifact_ids"] = artifact_ids

    async def on_phase_completed(self, event_data: dict) -> None:
        """Handle PhaseCompleted event.

        Updates phase with completion status and metrics.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        phase_id = event_data.get("phase_id")
        phases = existing.get("phases", [])

        found = self._find_phase(phases, phase_id or "")
        if found:
            _, phase = found
            self._update_phase_metrics(phase, event_data)
        else:
            new_phase = PhaseDetail.completed(phase_id or "", phase_id or "", event_data)
            phases.append(new_phase.to_dict())

        # Aggregate totals
        input_tokens = event_data.get("input_tokens", 0)
        output_tokens = event_data.get("output_tokens", 0)
        duration = event_data.get("duration_seconds", 0.0)
        cost = Decimal(str(event_data.get("cost_usd", "0")))
        self._aggregate_totals(existing, input_tokens, output_tokens, duration, cost)

        self._track_artifact(existing, event_data.get("artifact_id"))

        existing["phases"] = phases
        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_workflow_completed(self, event_data: dict) -> None:
        """Handle WorkflowCompleted event.

        Marks execution as completed with final metrics.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        existing["status"] = "completed"
        existing["completed_at"] = event_data.get("completed_at")

        # Update with final totals from event if provided
        if "total_input_tokens" in event_data:
            existing["total_input_tokens"] = event_data.get("total_input_tokens", 0)
        if "total_output_tokens" in event_data:
            existing["total_output_tokens"] = event_data.get("total_output_tokens", 0)
        if "total_cost_usd" in event_data:
            existing["total_cost_usd"] = str(event_data.get("total_cost_usd", "0"))
        if "total_duration_seconds" in event_data:
            existing["total_duration_seconds"] = event_data.get("total_duration_seconds", 0.0)
        if "artifact_ids" in event_data:
            existing["artifact_ids"] = event_data.get("artifact_ids", [])

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Handle WorkflowFailed event.

        Marks execution as failed with error information.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        existing["status"] = "failed"
        existing["completed_at"] = event_data.get("failed_at")
        existing["error_message"] = event_data.get("error_message")

        # Mark failed phase if specified
        failed_phase_id = event_data.get("failed_phase_id")
        if failed_phase_id:
            found = self._find_phase(existing.get("phases", []), failed_phase_id)
            if found:
                _, phase = found
                phase["status"] = "failed"
                phase["error_message"] = event_data.get("error_message")

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_execution_cancelled(self, event_data: dict) -> None:
        """Handle ExecutionCancelled event.

        Marks execution as cancelled via control plane.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        existing["status"] = "cancelled"
        existing["completed_at"] = event_data.get("cancelled_at")
        existing["error_message"] = event_data.get("reason") or "Cancelled by user"

        # Mark current phase as cancelled
        phase_id = event_data.get("phase_id")
        if phase_id:
            found = self._find_phase(existing.get("phases", []), phase_id)
            if found:
                _, phase = found
                phase["status"] = "cancelled"

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_workflow_interrupted(self, event_data: dict) -> None:
        """Handle WorkflowInterrupted event.

        Marks execution as interrupted (forceful stop via SIGINT) and captures
        the git SHA at the time of interruption.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        existing["status"] = "interrupted"
        existing["completed_at"] = event_data.get("interrupted_at")
        existing["error_message"] = event_data.get("reason") or "Interrupted by user"
        existing["git_sha"] = event_data.get("git_sha")

        # Mark interrupted phase
        phase_id = event_data.get("phase_id")
        if phase_id:
            found = self._find_phase(existing.get("phases", []), phase_id)
            if found:
                _, phase = found
                phase["status"] = "interrupted"

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionDetail | None:
        """Get execution detail by ID.

        Args:
            execution_id: The execution ID.

        Returns:
            Execution detail or None if not found.
        """
        data = await self._store.get(self.PROJECTION_NAME, execution_id)
        if data:
            return WorkflowExecutionDetail.from_dict(data)
        return None
