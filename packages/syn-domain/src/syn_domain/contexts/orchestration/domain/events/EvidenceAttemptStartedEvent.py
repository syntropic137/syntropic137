"""EvidenceAttemptStarted event - recorded BEFORE a dispatch is posted (plan §A.5, B3)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("EvidenceAttemptStarted", "v1")
class EvidenceAttemptStartedEvent(DomainEvent):
    """One attempt at one step. Any later process looks for ``dispatch_id``.

    ``not_after`` is the step's absolute deadline; retries share it.
    """

    execution_id: str
    gate_id: str
    step: int
    attempt: int
    dispatch_id: str
    started_at: datetime
    not_after: datetime
