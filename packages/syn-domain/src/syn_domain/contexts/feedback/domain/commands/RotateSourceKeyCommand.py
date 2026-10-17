"""RotateSourceKey command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("RotateSourceKey", "Replace a source's signing key")
class RotateSourceKeyCommand(BaseModel):
    """Replace a source's current key; the old one enters its overlap window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1, max_length=128)
    key_id: str = Field(min_length=1, max_length=64)
    verification_key: str = Field(min_length=1, max_length=256)
    rotated_at: datetime
