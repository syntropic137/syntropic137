"""TicketReopened event (ADR-076-feedback-ticketing). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("TicketReopened", "v1")
class TicketReopenedEvent(DomainEvent):
    """A closed or resolved ticket was reopened, e.g. on a regression."""

    ticket_id: str = Field(min_length=1)
    by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
