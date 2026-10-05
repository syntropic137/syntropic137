"""ExecutionTagsRemoved event (#967)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("ExecutionTagsRemoved", "v1")
class ExecutionTagsRemovedEvent(DomainEvent):
    """Tags were removed from an execution's current tags. Carries only the tags that were present.

    ``tags`` are already normalised by ``TagSet``.
    """

    execution_id: str
    workflow_id: str
    tags: list[str] = Field(default_factory=list)
