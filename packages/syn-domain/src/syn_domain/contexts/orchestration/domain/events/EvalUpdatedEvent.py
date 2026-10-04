"""EvalUpdated event (evals plan, #967)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.orchestration._shared.repository_baseline import (  # noqa: TC001
    RepositoryBaseline,
)


@event("EvalUpdated", "v1")
class EvalUpdatedEvent(DomainEvent):
    """Part of an eval changed. Carries only what changed.

    ``None`` means unchanged. ``tags_added`` and ``tags_removed`` hold only the
    tags that were actually new or actually present.
    """

    eval_id: str
    name: str | None = None
    goal: str | None = None
    baseline_repos: list[RepositoryBaseline] | None = None
    tags_added: list[str] = Field(default_factory=list)
    tags_removed: list[str] = Field(default_factory=list)
    updated_at: datetime
