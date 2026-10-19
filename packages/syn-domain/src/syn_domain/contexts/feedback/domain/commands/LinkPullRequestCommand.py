"""LinkPullRequest command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field


@command("LinkPullRequest", "Link a pull request to a ticket")
class LinkPullRequestCommand(BaseModel):
    """Link a pull request to a ticket. A repeat is a no-op."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    repository_id: int
    number: int = Field(gt=0)
