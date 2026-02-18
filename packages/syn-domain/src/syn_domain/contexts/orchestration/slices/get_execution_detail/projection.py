"""Projection for workflow execution detail view.

This projection maintains detailed execution state including per-phase metrics.
It's updated by WorkflowExecutionStarted, PhaseStarted, PhaseCompleted,
WorkflowCompleted, and WorkflowFailed events.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
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

from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)

# Event types this projection subscribes to
_SUBSCRIBED_EVENTS = {
    "WorkflowExecutionStarted",
    "PhaseStarted",
    "PhaseCompleted",
    "WorkflowCompleted",
    "WorkflowFailed",
}


class WorkflowExecutionDetailProjection(CheckpointedProjection):
    """Builds workflow execution detail read model from events.

    This projection maintains detailed execution state including:
    - Overall execution status and metrics
    - Per-phase execution details with individual metrics
    - Artifact references

    Implements CheckpointedProjection for per-projection position tracking.
    """

    PROJECTION_NAME = "workflow_execution_details"
    VERSION = 1

    def __init__(self, store: Any):  # Using Any to avoid circular import
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    # === CheckpointedProjection required methods ===

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version - increment to trigger rebuild."""
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        """Event types this projection handles."""
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
            if event_type == "WorkflowExecutionStarted":
                await self.on_workflow_execution_started(event_data)
            elif event_type == "PhaseStarted":
                await self.on_phase_started(event_data)
            elif event_type == "PhaseCompleted":
                await self.on_phase_completed(event_data)
            elif event_type == "WorkflowCompleted":
                await self.on_workflow_completed(event_data)
            elif event_type == "WorkflowFailed":
                await self.on_workflow_failed(event_data)

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
        """Get the projection name (deprecated, use get_name())."""
        return self.PROJECTION_NAME

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
        phase_name = event_data.get("phase_name", phase_id)

        # Check if phase already exists
        phases = existing.get("phases", [])
        phase_exists = any(p.get("phase_id") == phase_id for p in phases)

        if not phase_exists:
            phases.append(
                {
                    "phase_id": phase_id,
                    "name": phase_name,
                    "status": "running",
                    "session_id": event_data.get("session_id"),
                    "artifact_id": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "duration_seconds": 0.0,
                    "cost_usd": "0",
                    "started_at": event_data.get("started_at"),
                    "completed_at": None,
                    "error_message": None,
                }
            )
            existing["phases"] = phases
            await self._store.save(self.PROJECTION_NAME, execution_id, existing)

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

        # Find and update the phase
        phase_found = False
        for phase in phases:
            if phase.get("phase_id") == phase_id:
                phase["status"] = "completed"
                phase["session_id"] = event_data.get("session_id")
                phase["artifact_id"] = event_data.get("artifact_id")
                phase["input_tokens"] = event_data.get("input_tokens", 0)
                phase["output_tokens"] = event_data.get("output_tokens", 0)
                phase["total_tokens"] = event_data.get("total_tokens", 0)
                phase["duration_seconds"] = event_data.get("duration_seconds", 0.0)
                phase["cost_usd"] = str(event_data.get("cost_usd", "0"))
                phase["completed_at"] = event_data.get("completed_at")
                phase_found = True
                break

        # If phase not found (wasn't added by on_phase_started), add it now
        if not phase_found:
            phases.append(
                {
                    "phase_id": phase_id,
                    "name": phase_id,  # Use ID as name if not known
                    "status": "completed",
                    "session_id": event_data.get("session_id"),
                    "artifact_id": event_data.get("artifact_id"),
                    "input_tokens": event_data.get("input_tokens", 0),
                    "output_tokens": event_data.get("output_tokens", 0),
                    "total_tokens": event_data.get("total_tokens", 0),
                    "duration_seconds": event_data.get("duration_seconds", 0.0),
                    "cost_usd": str(event_data.get("cost_usd", "0")),
                    "started_at": None,
                    "completed_at": event_data.get("completed_at"),
                    "error_message": None,
                }
            )

        # Update totals
        input_tokens = event_data.get("input_tokens", 0)
        output_tokens = event_data.get("output_tokens", 0)
        duration = event_data.get("duration_seconds", 0.0)
        cost = Decimal(str(event_data.get("cost_usd", "0")))

        existing["total_input_tokens"] = existing.get("total_input_tokens", 0) + input_tokens
        existing["total_output_tokens"] = existing.get("total_output_tokens", 0) + output_tokens
        existing["total_duration_seconds"] = existing.get("total_duration_seconds", 0.0) + duration
        existing_cost = Decimal(str(existing.get("total_cost_usd", "0")))
        existing["total_cost_usd"] = str(existing_cost + cost)

        # Add artifact ID if present
        artifact_id = event_data.get("artifact_id")
        if artifact_id:
            artifact_ids = existing.get("artifact_ids", [])
            if artifact_id not in artifact_ids:
                artifact_ids.append(artifact_id)
            existing["artifact_ids"] = artifact_ids

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
            for phase in existing.get("phases", []):
                if phase.get("phase_id") == failed_phase_id:
                    phase["status"] = "failed"
                    phase["error_message"] = event_data.get("error_message")
                    break

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_execution_paused(self, event_data: dict) -> None:
        """Handle ExecutionPaused event.

        Marks execution as paused via control plane.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        existing["status"] = "paused"

        # Mark current phase as paused
        phase_id = event_data.get("phase_id")
        if phase_id:
            for phase in existing.get("phases", []):
                if phase.get("phase_id") == phase_id:
                    phase["status"] = "paused"
                    break

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_execution_resumed(self, event_data: dict) -> None:
        """Handle ExecutionResumed event.

        Marks execution as running again after pause.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if not existing:
            return

        existing["status"] = "running"

        # Mark current phase as running
        phase_id = event_data.get("phase_id")
        if phase_id:
            for phase in existing.get("phases", []):
                if phase.get("phase_id") == phase_id:
                    phase["status"] = "running"
                    break

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
            for phase in existing.get("phases", []):
                if phase.get("phase_id") == phase_id:
                    phase["status"] = "cancelled"
                    break

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
