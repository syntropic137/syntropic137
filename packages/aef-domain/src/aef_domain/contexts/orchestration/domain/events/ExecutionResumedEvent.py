"""ExecutionResumed event - emitted when workflow execution resumes."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("ExecutionResumed", "v1")
class ExecutionResumedEvent(DomainEvent):
    """Event emitted when workflow execution resumes after being paused."""

    workflow_id: str
    execution_id: str
    phase_id: str
    resumed_at: datetime
