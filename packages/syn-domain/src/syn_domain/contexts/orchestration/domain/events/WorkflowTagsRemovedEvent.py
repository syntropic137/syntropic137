"""WorkflowTagsRemoved event (#967)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("WorkflowTagsRemoved", "v1")
class WorkflowTagsRemovedEvent(DomainEvent):
    """Tags were removed from a workflow template. Carries only the tags that were present.

    ``tags`` are already normalised by ``TagSet``.
    """

    workflow_id: str
    tags: list[str] = Field(default_factory=list)
