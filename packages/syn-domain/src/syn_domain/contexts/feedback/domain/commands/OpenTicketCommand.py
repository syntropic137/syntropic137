"""OpenTicket command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import Priority, Provenance, Screening, TicketType


@command("OpenTicket", "Open a ticket from one screened submission")
class OpenTicketCommand(BaseModel):
    """Open a ticket from one screened submission. A retry with the same id is a no-op."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    number: int = Field(gt=0)
    submission_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: str | None  # None: the anonymous lane
    provenance: Provenance
    screening: Screening
    type: TicketType
    priority: Priority
    confidence: float = Field(ge=0.0, le=1.0)
    recurrence_of: str | None = None
