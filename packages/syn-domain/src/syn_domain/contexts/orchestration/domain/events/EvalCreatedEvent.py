"""EvalCreated event (evals plan, #967)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.orchestration._shared.repository_baseline import (  # noqa: TC001
    RepositoryBaseline,
)


@event("EvalCreated", "v1")
class EvalCreatedEvent(DomainEvent):
    """An eval was created. ``tags`` are already normalised by ``TagSet``."""

    eval_id: str
    name: str
    goal: str
    starting_workflow_id: str | None = None
    baseline_repos: list[RepositoryBaseline] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
