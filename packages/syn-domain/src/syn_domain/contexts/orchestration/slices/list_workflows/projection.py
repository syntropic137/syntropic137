"""Workflow List Projection.

This projection builds and maintains the WorkflowSummary read model
for workflow TEMPLATES. Templates don't have execution status.

For execution status, see WorkflowExecutionListProjection.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration._shared.tags import TagSet, replay_tag_edit
from syn_domain.contexts.orchestration.domain.events.WorkflowTagsAddedEvent import (
    WorkflowTagsAddedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTagsRemovedEvent import (
    WorkflowTagsRemovedEvent,
)
from syn_domain.contexts.orchestration.domain.read_models import WorkflowSummary
from syn_domain.pagination import ProjectionRecord, matches_search


class WorkflowListProjection(AutoDispatchProjection):
    """Builds workflow TEMPLATE list read model from events.

    This projection handles workflow template events only.
    Execution events are handled by WorkflowExecutionListProjection.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "workflow_summaries"
    VERSION = 5  # v5: tags (#967)

    def __init__(self, store: ProjectionStore):
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
            requires_repos=event_data.get("requires_repos", True),
            tags=TagSet.recorded(event_data.get("tags") or []).values,
        )
        await self._store.save(
            self.PROJECTION_NAME,
            summary.id,
            summary.to_dict(),
        )

    async def on_workflow_template_updated(self, event_data: dict) -> None:
        """Handle WorkflowTemplateUpdated - refresh the summary (issue #822).

        Reinstalling also clears the archived flag, mirroring the aggregate:
        an install brings back a template that a failed update had archived.
        runs_count belongs to the template, so it carries across.
        """
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        summary = WorkflowSummary(
            id=workflow_id,
            name=event_data["name"],
            workflow_type=event_data.get("workflow_type", ""),
            classification=event_data.get("classification", ""),
            phase_count=len(event_data.get("phases", [])),
            description=event_data.get("description"),
            created_at=(existing or {}).get("created_at") or event_data.get("created_at"),
            runs_count=(existing or {}).get("runs_count", 0),
            is_archived=False,
            requires_repos=event_data.get("requires_repos", True),
            # A reinstall replaces the template's tags wholesale, as the aggregate does.
            tags=TagSet.recorded(event_data.get("tags") or []).values,
        )
        await self._store.save(self.PROJECTION_NAME, summary.id, summary.to_dict())

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

    async def on_workflow_tags_added(self, event_data: WorkflowTagsAddedEvent) -> None:
        """Handle WorkflowTagsAdded (#967)."""
        event = WorkflowTagsAddedEvent.model_validate(event_data)
        await self._edit_tags(event.workflow_id, event.tags, added=True)

    async def on_workflow_tags_removed(self, event_data: WorkflowTagsRemovedEvent) -> None:
        """Handle WorkflowTagsRemoved (#967)."""
        event = WorkflowTagsRemovedEvent.model_validate(event_data)
        await self._edit_tags(event.workflow_id, event.tags, added=False)

    async def _edit_tags(self, workflow_id: str, tags: list[str], *, added: bool) -> None:
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            existing["tags"] = replay_tag_edit(existing.get("tags") or [], tags, added=added)
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
        search: str | None = None,
    ) -> list[WorkflowSummary]:
        """Query workflow template summaries with optional filtering.

        Args:
            workflow_type_filter: Filter by workflow type
            limit: Maximum results
            offset: Pagination offset
            order_by: Sort field (prefix with - for descending)
            include_archived: If True, include archived templates. Defaults to False.
            search: Case-insensitive substring matched against name and id.

        Returns:
            List of matching WorkflowSummary objects
        """
        rows = await self._matching(workflow_type_filter, include_archived, search, order_by)
        return [WorkflowSummary.from_dict(d) for d in rows[offset : offset + limit]]

    async def count(
        self,
        workflow_type_filter: str | None = None,
        include_archived: bool = False,
        search: str | None = None,
    ) -> int:
        """Count all matching templates, ignoring pagination."""
        return len(await self._matching(workflow_type_filter, include_archived, search))

    async def _matching(
        self,
        workflow_type_filter: str | None,
        include_archived: bool,
        search: str | None,
        order_by: str | None = None,
    ) -> list[ProjectionRecord]:
        """Every template matching the filters, before pagination.

        Shared by ``query`` and ``count`` so the two cannot drift: a total
        computed under different filters than the page it describes is worse
        than no total at all. That is also why pagination happens here in
        Python rather than in the store: ``search`` is a substring match the
        store's equality filters cannot express, and it has to run before the
        page is cut or it only ever searches the page (#1159 left this list
        doing exactly that in the browser).

        COST: this fetches every matching row, O(n) per request. Fine at the
        current scale (tens of templates). The store protocol has neither a
        ``count`` nor a substring filter; adding them touches both adapters
        and the test doubles, so it is not bundled in here.
        """
        filters: dict[str, str | bool] = {}
        if workflow_type_filter:
            filters["workflow_type"] = workflow_type_filter
        if not include_archived:
            filters["is_archived"] = False
        rows = await self._store.query(
            self.PROJECTION_NAME,
            filters=filters or None,
            order_by=order_by,
            limit=None,
            offset=0,
        )
        return [r for r in rows if matches_search(search, r.get("name"), r.get("id"))]
