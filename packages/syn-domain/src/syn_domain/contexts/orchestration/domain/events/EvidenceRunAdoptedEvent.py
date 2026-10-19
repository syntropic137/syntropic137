"""EvidenceRunAdopted event - an attempt's run was found on the forge (plan §A.5)."""

from __future__ import annotations

from event_sourcing import DomainEvent, event


@event("EvidenceRunAdopted", "v1")
class EvidenceRunAdoptedEvent(DomainEvent):
    """The run that answers attempt ``attempt`` of step ``step``."""

    execution_id: str
    gate_id: str
    step: int
    attempt: int
    run_id: int
    run_url: str
