"""TicketReportDetached event (ADR-076). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("TicketReportDetached", "v1")
class TicketReportDetachedEvent(DomainEvent):
    """The owner took an over-merged submission back off a ticket."""

    ticket_id: str = Field(min_length=1)
    submission_id: str = Field(min_length=1)
    by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
