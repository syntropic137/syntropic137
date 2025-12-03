"""Workflow List Projection.

This projection builds and maintains the WorkflowSummary read model
by processing relevant domain events. It uses an injected
ProjectionStoreProtocol for persistence.
"""

from typing import Any

from aef_domain.contexts.workflows.domain.read_models import WorkflowSummary


class WorkflowListProjection:
    """Builds workflow list read model from events.

    This projection subscribes to workflow-related events and
    maintains an optimized view for listing workflows.

    The projection is responsible for:
    1. Processing events in order
    2. Maintaining read model state
    3. Providing query access to the data
    """

    PROJECTION_NAME = "workflow_summaries"

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
        """Handle WorkflowCreated event.

        Creates a new workflow summary record.

        Args:
            event_data: Event payload containing workflow data
        """
        summary = WorkflowSummary(
            id=event_data["workflow_id"],
            name=event_data["name"],
            workflow_type=event_data.get("workflow_type", ""),
            classification=event_data.get("classification", ""),
            status="pending",
            phase_count=len(event_data.get("phases", [])),
            description=event_data.get("description"),
            created_at=event_data.get("created_at"),
        )
        await self._store.save(
            self.PROJECTION_NAME,
            summary.id,
            summary.to_dict(),
        )

    async def on_phase_started(self, event_data: dict) -> None:
        """Handle PhaseStarted event.

        Updates workflow status to in_progress if it was pending.

        Args:
            event_data: Event payload containing workflow_id
        """
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing and existing.get("status") == "pending":
            existing["status"] = "in_progress"
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def on_workflow_completed(self, event_data: dict) -> None:
        """Handle WorkflowCompleted event.

        Updates workflow status to completed.

        Args:
            event_data: Event payload containing workflow_id
        """
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            existing["status"] = "completed"
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Handle WorkflowFailed event.

        Updates workflow status to failed.

        Args:
            event_data: Event payload containing workflow_id
        """
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            existing["status"] = "failed"
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def get_all(self) -> list[WorkflowSummary]:
        """Get all workflow summaries.

        Returns:
            List of WorkflowSummary objects
        """
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [WorkflowSummary.from_dict(d) for d in data]

    async def query(
        self,
        status_filter: str | None = None,
        workflow_type_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "-created_at",
    ) -> list[WorkflowSummary]:
        """Query workflow summaries with optional filtering.

        Args:
            status_filter: Filter by status
            workflow_type_filter: Filter by workflow type
            limit: Maximum results
            offset: Pagination offset
            order_by: Sort field (prefix with - for descending)

        Returns:
            List of matching WorkflowSummary objects
        """
        filters = {}
        if status_filter:
            filters["status"] = status_filter
        if workflow_type_filter:
            filters["workflow_type"] = workflow_type_filter

        data = await self._store.query(
            self.PROJECTION_NAME,
            filters=filters if filters else None,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
        return [WorkflowSummary.from_dict(d) for d in data]
