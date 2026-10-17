"""TicketReportAdded event (ADR-076). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("TicketReportAdded", "v1")
class TicketReportAddedEvent(DomainEvent):
    """A submission joined a ticket as a near duplicate."""

    ticket_id: str = Field(min_length=1)
    submission_id: str = Field(min_length=1)
    source_id: str | None  # None: the anonymous lane
    similarity: float = Field(ge=0.0, le=1.0)
