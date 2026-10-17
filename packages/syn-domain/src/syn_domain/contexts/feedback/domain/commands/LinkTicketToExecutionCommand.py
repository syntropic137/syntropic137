"""LinkTicketToExecution command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("LinkTicketToExecution", "Link a ticket to an execution")
class LinkTicketToExecutionCommand(BaseModel):
    """Link a ticket to an execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
