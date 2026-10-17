"""TicketReleasedFromQuarantine event (ADR-076-feedback-ticketing). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("TicketReleasedFromQuarantine", "v1")
class TicketReleasedFromQuarantineEvent(DomainEvent):
    """The owner released a quarantined ticket's text."""

    ticket_id: str = Field(min_length=1)
    by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
