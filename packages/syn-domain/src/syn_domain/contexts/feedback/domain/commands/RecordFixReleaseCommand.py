"""RecordFixRelease command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("RecordFixRelease", "Record that a published release contains the fix")
class RecordFixReleaseCommand(BaseModel):
    """Record that a published release contains the fix."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    release_tag: str = Field(min_length=1)
    version: str = Field(min_length=1)
    commit: str = Field(min_length=1)
