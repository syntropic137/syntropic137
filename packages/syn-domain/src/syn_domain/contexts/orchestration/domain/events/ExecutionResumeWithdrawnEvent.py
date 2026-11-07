"""ExecutionResumeWithdrawn event (#1677)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves it at runtime

from event_sourcing import DomainEvent, event


@event("ExecutionResumeWithdrawn", "v1")
class ExecutionResumeWithdrawnEvent(DomainEvent):
    """A parent's admitted resume was withdrawn before its child existed.

    Recorded on the PARENT's stream, beside the `ExecutionResumed` it
    withdraws: the child's stream must still open with NoStream if it ever
    starts, and a resume has no request stream of its own. Terminal for the
    resume start: nothing starts the child after this, in this process or after
    a restart. A child that already started is cancelled, not withdrawn.
    """

    execution_id: str
    resume_execution_id: str
    reason: str | None = None
    withdrawn_at: datetime
