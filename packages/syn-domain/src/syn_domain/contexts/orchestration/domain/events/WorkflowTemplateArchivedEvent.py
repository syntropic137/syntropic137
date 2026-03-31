"""WorkflowTemplateArchived event - represents the fact that a workflow template was archived."""

from __future__ import annotations

from event_sourcing import DomainEvent, event


@event("WorkflowTemplateArchived", "v1")
class WorkflowTemplateArchivedEvent(DomainEvent):
    """Event emitted when a workflow template is archived (soft-deleted).

    Archived templates are excluded from list views by default
    but remain accessible by ID for historical reference.
    """

    workflow_id: str
    archived_by: str = ""
