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
        """Handle WorkflowExecutionStarted - mark workflow as started."""
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            existing["status"] = "in_progress"
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
        """Handle PhaseCompleted - update phase status in phases list."""
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            # Update phase status in the phases list
            phase_id = event_data.get("phase_id")
            for phase in existing.get("phases", []):
                if phase.get("phase_id") == phase_id:
                    phase["status"] = "completed"
                    break
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
