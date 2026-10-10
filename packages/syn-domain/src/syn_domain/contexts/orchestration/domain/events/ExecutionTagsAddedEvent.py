"""ExecutionTagsAdded event (#967)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("ExecutionTagsAdded", "v1")
class ExecutionTagsAddedEvent(DomainEvent):
    """Tags were added to an execution after launch. Carries only the tags that were new.

    ``tags`` are already normalised by ``TagSet``.
    """

    execution_id: str
    workflow_id: str
    tags: list[str] = Field(default_factory=list)
