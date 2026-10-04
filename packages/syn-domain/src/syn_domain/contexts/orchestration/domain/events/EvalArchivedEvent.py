"""EvalArchived event (evals plan, #967)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event


@event("EvalArchived", "v1")
class EvalArchivedEvent(DomainEvent):
    """The eval was retired. It stays readable and keeps its runs."""

    eval_id: str
    archived_by: str = ""
    archived_at: datetime
