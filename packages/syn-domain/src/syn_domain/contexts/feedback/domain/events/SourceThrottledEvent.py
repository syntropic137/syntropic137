"""SourceThrottled event (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("SourceThrottled", "v1")
class SourceThrottledEvent(DomainEvent):
    """Intake rejects this source's submissions at the quota step until the owner lifts it."""

    source_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=256)
