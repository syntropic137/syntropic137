"""TicketOpened event (ADR-076-feedback-ticketing). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.feedback._shared.value_objects import Priority, Provenance, Screening, TicketType


@event("TicketOpened", "v1")
class TicketOpenedEvent(DomainEvent):
    """A ticket was opened from one screened submission. Its first Report."""

    ticket_id: str = Field(min_length=1)
    number: int = Field(gt=0)
    submission_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: str | None  # None: the anonymous lane
    provenance: Provenance
    screening: Screening
    type: TicketType
    priority: Priority
    confidence: float = Field(ge=0.0, le=1.0)
    recurrence_of: str | None = None
