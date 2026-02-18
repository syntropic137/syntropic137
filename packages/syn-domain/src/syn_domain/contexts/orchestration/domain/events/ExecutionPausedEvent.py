"""ExecutionPaused event - emitted when workflow execution is paused."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("ExecutionPaused", "v1")
class ExecutionPausedEvent(DomainEvent):
    """Event emitted when workflow execution is paused via control plane.

    The execution can be resumed later with ExecutionResumedEvent.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    paused_at: datetime
    reason: str | None = None
