"""SourceKeyRotated event (ADR-076-feedback-ticketing). Public key material only: never a secret."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("SourceKeyRotated", "v1")
class SourceKeyRotatedEvent(DomainEvent):
    """A source's current key was replaced.

    The retired key stays valid until ``rotated_at`` plus the overlap window,
    which is a setting of the verifier, not a fact recorded here: changing the
    window must not need a new event.
    """

    source_id: str = Field(min_length=1, max_length=128)
    retired_key_id: str = Field(min_length=1, max_length=64)
    key_id: str = Field(min_length=1, max_length=64)
    verification_key: str = Field(min_length=1, max_length=256)
    rotated_at: datetime
