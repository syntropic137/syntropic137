"""CloseTicket command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import CloseReason


@command("CloseTicket", "Close a ticket")
class CloseTicketCommand(BaseModel):
    """Close a ticket."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    reason: CloseReason
    duplicate_of: str | None = None
