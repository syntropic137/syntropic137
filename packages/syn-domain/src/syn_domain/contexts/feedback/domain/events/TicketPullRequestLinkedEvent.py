"""TicketPullRequestLinked event (ADR-076-feedback-ticketing). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("TicketPullRequestLinked", "v1")
class TicketPullRequestLinkedEvent(DomainEvent):
    """A pull request was linked to a ticket as a fix for it."""

    ticket_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    repository_id: int
    number: int = Field(gt=0)
