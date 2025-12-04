"""Projection for workflow detail view."""

from typing import Any

from aef_domain.contexts.workflows.domain.read_models.workflow_detail import (
    WorkflowDetail,
)


class WorkflowDetailProjection:
    """Builds workflow detail read model from events.

    This projection maintains detailed workflow state including phases,
    execution timestamps, and completion status.
    """

    PROJECTION_NAME = "workflow_details"

    def __init__(self, store: Any):  # Using Any to avoid circular import
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_workflow_created(self, event_data: dict) -> None:
        """Handle WorkflowCreated event."""
        workflow_id = event_data.get("workflow_id", "")
        detail = WorkflowDetail(
            id=workflow_id,
            name=event_data.get("name", ""),
            workflow_type=event_data.get("workflow_type", ""),
            classification=event_data.get("classification", ""),
            status="pending",
            phases=event_data.get("phases", []),
            description=event_data.get("description"),
            created_at=event_data.get("created_at"),
            started_at=None,
            completed_at=None,
        )
        await self._store.save(self.PROJECTION_NAME, workflow_id, detail.to_dict())

    async def on_workflow_execution_started(self, event_data: dict) -> None:
        """Handle WorkflowExecutionStarted - record execution metadata.

        Note: Status is NOT changed here to be consistent with list projection.
        Status changes to in_progress on phase_started when actual work begins.
        This prevents incomplete/failed executions from overriding valid states.
        """
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            # Only update started_at, not status
            # Status changes to in_progress on phase_started (consistent with list)
            existing["started_at"] = event_data.get("started_at")
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def on_phase_started(self, event_data: dict) -> None:
        """Handle PhaseStarted - update status if first phase."""
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing and existing.get("status") == "pending":
            existing["status"] = "in_progress"
            existing["started_at"] = event_data.get("started_at")
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def on_phase_completed(self, event_data: dict) -> None:
        """Handle PhaseCompleted - update phase status and metrics in phases list."""
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            # Update phase status and metrics in the phases list
            phase_id = event_data.get("phase_id")
            for phase in existing.get("phases", []):
                # Support both 'phase_id' and 'id' keys for robustness
                stored_phase_id = phase.get("phase_id") or phase.get("id")
                if stored_phase_id == phase_id:
                    phase["status"] = "completed"
                    # Store phase metrics from event
                    phase["input_tokens"] = event_data.get("input_tokens", 0)
                    phase["output_tokens"] = event_data.get("output_tokens", 0)
                    phase["total_tokens"] = event_data.get("total_tokens", 0)
                    phase["duration_seconds"] = event_data.get("duration_seconds", 0.0)
                    phase["cost_usd"] = str(event_data.get("cost_usd", "0"))
                    phase["session_id"] = event_data.get("session_id")
                    break

            # Track completed phase count
            completed_count = sum(
                1 for p in existing.get("phases", []) if p.get("status") == "completed"
            )
            existing["completed_phases"] = completed_count

            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def on_workflow_completed(self, event_data: dict) -> None:
        """Handle WorkflowCompleted event."""
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            existing["status"] = "completed"
            existing["completed_at"] = event_data.get("completed_at")
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Handle WorkflowFailed event."""
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            existing["status"] = "failed"
            existing["error_message"] = event_data.get("error_message")
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def get_by_id(self, workflow_id: str) -> WorkflowDetail | None:
        """Get a workflow by ID."""
        data = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if data:
            return WorkflowDetail.from_dict(data)
        return None
