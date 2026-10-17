"""ThrottleSource command (ADR-076-feedback-ticketing). Dispatched by SourceGuard (plan s2.6)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("ThrottleSource", "Throttle a source")
class ThrottleSourceCommand(BaseModel):
    """Throttle a source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=256)
