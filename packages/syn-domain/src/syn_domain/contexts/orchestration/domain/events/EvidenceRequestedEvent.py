"""EvidenceRequested event - the aggregate held a transition for evidence (plan §A.4)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    EvidencePlanStep,  # noqa: TC001 - needed at runtime for Pydantic
)


@event("EvidenceRequested", "v1")
class EvidenceRequestedEvent(DomainEvent):
    """Emitted INSTEAD of `NextPhaseReady` when a gate opens after a collected phase.

    Carries the decision already taken (the held next phase and its skips)
    and the whole ordered plan, so the gate's last settle can emit
    `NextPhaseReady` without deciding anything again.
    """

    workflow_id: str
    execution_id: str
    gate_id: str
    after_phase_id: str
    next_phase_id: str
    next_phase_order: int
    skipped_phase_ids: list[str] = Field(default_factory=list)
    steps: list[EvidencePlanStep]
    requested_at: datetime
