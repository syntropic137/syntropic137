"""ReleaseTicketFromQuarantine command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("ReleaseTicketFromQuarantine", "Release a quarantined ticket")
class ReleaseTicketFromQuarantineCommand(BaseModel):
    """Release a quarantined ticket."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
