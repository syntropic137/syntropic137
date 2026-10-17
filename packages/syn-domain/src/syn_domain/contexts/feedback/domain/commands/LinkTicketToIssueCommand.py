"""LinkTicketToIssue command (ADR-076)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("LinkTicketToIssue", "Link a ticket to a GitHub issue")
class LinkTicketToIssueCommand(BaseModel):
    """Link a ticket to a GitHub issue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    repository_id: int
    number: int = Field(gt=0)
