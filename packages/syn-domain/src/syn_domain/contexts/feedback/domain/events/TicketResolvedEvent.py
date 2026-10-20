"""TicketResolved event (ADR-076-feedback-ticketing). Ids and hashes only: never reporter text."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.feedback._shared.value_objects import ResolutionRule  # noqa: TC001


@event("TicketResolved", "v1")
class TicketResolvedEvent(DomainEvent):
    """The Resolution Policy became true. Names the version that holds the fix."""

    ticket_id: str = Field(min_length=1)
    rule: ResolutionRule
    version: str = Field(min_length=1)
