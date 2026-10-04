"""WorkflowDefaultEvalSet event (evals plan, #967)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event


@event("WorkflowDefaultEvalSet", "v1")
class WorkflowDefaultEvalSetEvent(DomainEvent):
    """A workflow's default eval changed. ``eval_id`` None means it was cleared."""

    workflow_id: str
    eval_id: str | None = None
