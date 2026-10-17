"""TicketClosed event (ADR-076-feedback-ticketing). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.feedback._shared.value_objects import CloseReason  # noqa: TC001


@event("TicketClosed", "v1")
class TicketClosedEvent(DomainEvent):
    """A ticket was closed without being resolved."""

    ticket_id: str = Field(min_length=1)
    reason: CloseReason
    duplicate_of: str | None = None
