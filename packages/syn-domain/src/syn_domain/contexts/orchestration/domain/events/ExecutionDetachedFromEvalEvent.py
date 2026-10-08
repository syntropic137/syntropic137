"""ExecutionDetachedFromEval event (evals plan, #967)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic field type

from event_sourcing import DomainEvent, event


@event("ExecutionDetachedFromEval", "v1")
class ExecutionDetachedFromEvalEvent(DomainEvent):
    """An execution left the eval it belonged to.

    ``association_kind`` is how it had joined: ``launched`` or ``attached``.
    """

    execution_id: str
    workflow_id: str
    eval_id: str
    association_kind: str
    detached_at: datetime
