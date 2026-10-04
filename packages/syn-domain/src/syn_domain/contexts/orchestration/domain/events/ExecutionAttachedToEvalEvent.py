"""ExecutionAttachedToEval event (evals plan, #967)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic field type

from event_sourcing import DomainEvent, event


@event("ExecutionAttachedToEval", "v1")
class ExecutionAttachedToEvalEvent(DomainEvent):
    """An execution joined an eval after it was launched (``association_kind=attached``).

    A launch into an eval is recorded on ``WorkflowExecutionStarted`` instead.
    Nothing here describes the run's repository state: an attached run keeps
    the task, workflow snapshot and starting commits it was launched with.
    """

    execution_id: str
    workflow_id: str
    eval_id: str
    attached_at: datetime
