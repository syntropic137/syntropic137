"""TicketLinkedToExecution event (ADR-076). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("TicketLinkedToExecution", "v1")
class TicketLinkedToExecutionEvent(DomainEvent):
    """A ticket was linked to a workflow execution working on it."""

    ticket_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
