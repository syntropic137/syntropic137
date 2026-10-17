"""TicketLinkedToIssue event (ADR-076-feedback-ticketing). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("TicketLinkedToIssue", "v1")
class TicketLinkedToIssueEvent(DomainEvent):
    """A ticket was linked to a GitHub issue."""

    ticket_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    repository_id: int
    number: int = Field(gt=0)
