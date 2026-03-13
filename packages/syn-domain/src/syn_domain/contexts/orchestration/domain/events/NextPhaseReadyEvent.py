"""NextPhaseReady event - aggregate decided another phase should run."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("NextPhaseReady", "v1")
class NextPhaseReadyEvent(DomainEvent):
    """Event emitted by the aggregate when it determines the next phase should run.

    This is the aggregate's decision — not the processor's. The processor
    reads the to-do list and dispatches provisioning for the next phase.
    """

    workflow_id: str
    execution_id: str
    completed_phase_id: str
    next_phase_id: str
    next_phase_order: int
    decided_at: datetime
