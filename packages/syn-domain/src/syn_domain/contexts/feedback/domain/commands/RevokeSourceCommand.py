"""RevokeSource command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("RevokeSource", "Revoke a source")
class RevokeSourceCommand(BaseModel):
    """Revoke a source. Terminal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1, max_length=128)
    by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=256)
