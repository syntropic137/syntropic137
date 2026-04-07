"""Workflow List Projection.

This projection builds and maintains the WorkflowSummary read model
for workflow TEMPLATES. Templates don't have execution status.

For execution status, see WorkflowExecutionListProjection.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.domain.read_models import WorkflowSummary


class WorkflowListProjection(AutoDispatchProjection):
    """Builds workflow TEMPLATE list read model from events.

    This projection handles workflow template events only.
    Execution events are handled by WorkflowExecutionListProjection.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "workflow_summaries"
    VERSION = 3  # Bumped: added archive support with is_archived field

    def __init__(self, store: ProjectionStoreProtocol):
        """Initialize with a projection store."""
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

    async def on_workflow_template_created(self, event_data: dict) -> None:
        """Handle WorkflowTemplateCreated event.

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
            is_archived=False,
        )
        await self._store.save(
            self.PROJECTION_NAME,
            summary.id,
            summary.to_dict(),
        )

    async def on_workflow_template_archived(self, event_data: dict) -> None:
        """Handle WorkflowTemplateArchived event.

        Marks the workflow template as archived in the read model.
        """
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            existing["is_archived"] = True
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

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

    async def get_all(self, include_archived: bool = False) -> list[WorkflowSummary]:
        """Get all workflow template summaries.

        Args:
            include_archived: If True, include archived templates. Defaults to False.
        """
        data = await self._store.get_all(self.PROJECTION_NAME)
        summaries = [WorkflowSummary.from_dict(d) for d in data]
        if not include_archived:
            summaries = [s for s in summaries if not s.is_archived]
        return summaries

    async def query(
        self,
        workflow_type_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "-created_at",
        include_archived: bool = False,
    ) -> list[WorkflowSummary]:
        """Query workflow template summaries with optional filtering.

        Args:
            workflow_type_filter: Filter by workflow type
            limit: Maximum results
            offset: Pagination offset
            order_by: Sort field (prefix with - for descending)
            include_archived: If True, include archived templates. Defaults to False.

        Returns:
            List of matching WorkflowSummary objects
        """
        filters = {}
        if workflow_type_filter:
            filters["workflow_type"] = workflow_type_filter

        if not include_archived:
            filters["is_archived"] = False

        data = await self._store.query(
            self.PROJECTION_NAME,
            filters=filters if filters else None,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
        return [WorkflowSummary.from_dict(d) for d in data]
