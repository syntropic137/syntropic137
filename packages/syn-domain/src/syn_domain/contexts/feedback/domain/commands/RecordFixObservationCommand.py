"""RecordFixObservation command (ADR-076)."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("RecordFixObservation", "Record what one source observed about the fix")
class RecordFixObservationCommand(BaseModel):
    """Record what one source observed about the fix."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    commit: str = Field(min_length=1)
    version: str = Field(min_length=1)
    contains_fix: bool
    observed_at: datetime
