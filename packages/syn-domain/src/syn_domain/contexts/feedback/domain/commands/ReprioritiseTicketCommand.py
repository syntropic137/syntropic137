"""ReprioritiseTicket command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import Priority  # noqa: TC001


@command("ReprioritiseTicket", "Change a ticket's priority")
class ReprioritiseTicketCommand(BaseModel):
    """Change a ticket's priority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    priority: Priority
    by: str = Field(min_length=1, max_length=128)
