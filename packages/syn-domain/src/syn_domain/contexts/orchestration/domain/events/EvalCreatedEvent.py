"""EvalCreated event (evals plan, #967)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event
from pydantic import BaseModel, ConfigDict, Field


class RepositoryPayload(BaseModel):
    """Which repository, as recorded: the owner and name only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owner: str
    name: str


class BaselineRepoPayload(BaseModel):
    """One pinned repository as recorded, in primitives.

    Events are pure data, so this mirrors ``RepositoryBaseline`` field for field
    instead of importing it; the aggregate maps between the two. The
    serialized shape is the same, so a stored event reads either way.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: RepositoryPayload
    requested_ref: str
    commit_sha: str


@event("EvalCreated", "v1")
class EvalCreatedEvent(DomainEvent):
    """An eval was created. ``tags`` are already normalised by ``TagSet``."""

    eval_id: str
    name: str
    goal: str
    starting_workflow_id: str | None = None
    baseline_repos: list[BaselineRepoPayload] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
