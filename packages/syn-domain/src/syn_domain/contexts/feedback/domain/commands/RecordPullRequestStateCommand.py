"""RecordPullRequestState command (ADR-076-feedback-ticketing)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import PullRequestState  # noqa: TC001


@command("RecordPullRequestState", "Record an observed state of a linked pull request")
class RecordPullRequestStateCommand(BaseModel):
    """Record an observed state of a linked pull request.

    The PR is addressed by ``repository_id``; ``repository`` is only the name it
    had when observed, so a rename still reaches the PR that was linked.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    repository_id: int
    number: int = Field(gt=0)
    state: PullRequestState
    merge_commit: str | None = None
    observed_at: datetime
