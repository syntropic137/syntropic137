"""NextPhaseReady event - aggregate decided another phase should run."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event
from pydantic import Field


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
    #: Phases between the completed one and the next that will never run,
    #: because a review verdict made them unnecessary (PC-63). Recorded here,
    #: on the decision, so a skipped phase is distinguishable from one that
    #: has simply not started yet.
    skipped_phase_ids: list[str] = Field(default_factory=list)
