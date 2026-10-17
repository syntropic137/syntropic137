"""SourceThrottleLifted event (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("SourceThrottleLifted", "v1")
class SourceThrottleLiftedEvent(DomainEvent):
    """The owner lifted a source's throttle."""

    source_id: str = Field(min_length=1, max_length=128)
    by: str = Field(min_length=1, max_length=128)
