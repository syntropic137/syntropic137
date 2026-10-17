"""TicketFixObserved event (ADR-076). Ids and hashes only: never reporter text."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("TicketFixObserved", "v1")
class TicketFixObservedEvent(DomainEvent):
    """One source reported whether its deployment contains the fix."""

    ticket_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    commit: str = Field(min_length=1)
    version: str = Field(min_length=1)
    contains_fix: bool
    observed_at: datetime
