"""DetachReport command (ADR-076)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("DetachReport", "Take an over-merged submission back off a ticket")
class DetachReportCommand(BaseModel):
    """Take an over-merged submission back off a ticket."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    submission_id: str = Field(min_length=1)
    by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
