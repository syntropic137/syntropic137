"""SourceEnrolled event (ADR-076-feedback-ticketing). Public key material only: never a secret."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("SourceEnrolled", "v1")
class SourceEnrolledEvent(DomainEvent):
    """A deployment was enrolled and may sign submissions with ``key_id``.

    ``verification_key`` is the base64 public key under Ed25519, or the hash of
    the shared secret if D2 picks HMAC. Never the signing key itself.
    """

    source_id: str = Field(min_length=1, max_length=128)
    key_id: str = Field(min_length=1, max_length=64)
    verification_key: str = Field(min_length=1, max_length=256)
    daily_quota: int = Field(gt=0)
    enrolled_at: datetime
