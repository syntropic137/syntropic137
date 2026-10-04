"""ExecutionRequested event (#1557)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves it at runtime

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("ExecutionRequested", "v1")
class ExecutionRequestedEvent(DomainEvent):
    """A direct start was admitted, durably, before the caller was told so.

    Carries everything the start needs, as primitives, so a restart can start
    it from this event alone. The execution it names does not exist yet: its
    own stream opens when the start gets an execution-budget slot.
    """

    execution_id: str
    workflow_id: str
    inputs: dict[str, str] = Field(default_factory=dict)
    task: str | None = None
    repos: list[str] = Field(default_factory=list)
    """Repository slugs (`owner/name`), as `RepositoryRef.slug` writes them."""
    tags: list[str] = Field(default_factory=list)
    requested_at: datetime
