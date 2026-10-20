"""SourceRevoked event (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("SourceRevoked", "v1")
class SourceRevokedEvent(DomainEvent):
    """Terminal: no key of this source verifies again, including one inside a rotation overlap."""

    source_id: str = Field(min_length=1, max_length=128)
    by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=256)
