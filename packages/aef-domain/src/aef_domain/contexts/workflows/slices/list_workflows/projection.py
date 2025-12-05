"""Workflow List Projection.

This projection builds and maintains the WorkflowSummary read model
for workflow TEMPLATES. Templates don't have execution status.

For execution status, see WorkflowExecutionListProjection.
"""

from typing import Any

from aef_domain.contexts.workflows.domain.read_models import WorkflowSummary


class WorkflowListProjection:
    """Builds workflow TEMPLATE list read model from events.

    This projection handles workflow template events only.
    Execution events are handled by WorkflowExecutionListProjection.
    """

    PROJECTION_NAME = "workflow_summaries"

    def __init__(self, store: Any):
        """Initialize with a projection store."""
        self._store = store

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_workflow_created(self, event_data: dict) -> None:
        """Handle WorkflowCreated event.

        Creates a new workflow template summary.
        Templates don't have status - they're just definitions.
        """
        summary = WorkflowSummary(
            id=event_data["workflow_id"],
            name=event_data["name"],
            workflow_type=event_data.get("workflow_type", ""),
            classification=event_data.get("classification", ""),
            phase_count=len(event_data.get("phases", [])),
            description=event_data.get("description"),
            created_at=event_data.get("created_at"),
            runs_count=0,
        )
        await self._store.save(
            self.PROJECTION_NAME,
            summary.id,
            summary.to_dict(),
        )

    async def on_workflow_execution_started(self, event_data: dict) -> None:
        """Handle WorkflowExecutionStarted event.

        Increments runs_count for the workflow template.
        """
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            existing["runs_count"] = existing.get("runs_count", 0) + 1
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def get_all(self) -> list[WorkflowSummary]:
        """Get all workflow template summaries."""
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [WorkflowSummary.from_dict(d) for d in data]

    async def query(
        self,
        workflow_type_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "-created_at",
    ) -> list[WorkflowSummary]:
        """Query workflow template summaries with optional filtering.

        Args:
            workflow_type_filter: Filter by workflow type
            limit: Maximum results
            offset: Pagination offset
            order_by: Sort field (prefix with - for descending)

        Returns:
            List of matching WorkflowSummary objects
        """
        filters = {}
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
