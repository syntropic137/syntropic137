"""AddReport command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import Screening


@command("AddReport", "Add a submission to a ticket as a Report")
class AddReportCommand(BaseModel):
    """Add a submission to a ticket as a Report. A member already present is a no-op."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    submission_id: str = Field(min_length=1)
    source_id: str | None  # None: the anonymous lane
    similarity: float = Field(ge=0.0, le=1.0)
    screening: Screening  # the submission's own screening
