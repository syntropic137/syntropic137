"""EnrollSource command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


@command("EnrollSource", "Enroll a deployment as a feedback source")
class EnrollSourceCommand(BaseModel):
    """Enroll a deployment. ``aggregate_id`` is its ``source_instance_id``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1, max_length=128)
    key_id: str = Field(min_length=1, max_length=64)
    verification_key: str = Field(min_length=1, max_length=256)
    daily_quota: int = Field(gt=0)
    enrolled_at: AwareDatetime
