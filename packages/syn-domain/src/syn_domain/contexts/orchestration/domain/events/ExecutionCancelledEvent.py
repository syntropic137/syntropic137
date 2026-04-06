"""ExecutionCancelled event - emitted when workflow execution is cancelled."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event


@event("ExecutionCancelled", "v1")
class ExecutionCancelledEvent(DomainEvent):
    """Event emitted when workflow execution is cancelled via control plane.

    Unlike WorkflowFailedEvent, this is an intentional user-initiated stop.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    cancelled_at: datetime
    reason: str | None = None
