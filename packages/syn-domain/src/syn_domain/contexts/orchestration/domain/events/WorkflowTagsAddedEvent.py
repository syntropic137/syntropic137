"""WorkflowTagsAdded event (#967)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("WorkflowTagsAdded", "v1")
class WorkflowTagsAddedEvent(DomainEvent):
    """Tags were added to a workflow template. Carries only the tags that were new.

    ``tags`` are already normalised by ``TagSet``.
    """

    workflow_id: str
    tags: list[str] = Field(default_factory=list)
