"""TicketFixReleased event (ADR-076-feedback-ticketing). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("TicketFixReleased", "v1")
class TicketFixReleasedEvent(DomainEvent):
    """A published release contains the fix."""

    ticket_id: str = Field(min_length=1)
    release_tag: str = Field(min_length=1)
    version: str = Field(min_length=1)
    commit: str = Field(min_length=1)
