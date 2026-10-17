"""TicketReprioritised event (ADR-076-feedback-ticketing). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.feedback._shared.value_objects import Priority  # noqa: TC001


@event("TicketReprioritised", "v1")
class TicketReprioritisedEvent(DomainEvent):
    """A ticket's priority changed."""

    ticket_id: str = Field(min_length=1)
    priority: Priority
    by: str = Field(min_length=1, max_length=128)
