"""PhaseDeadlineSet event - the time a phase's agent is killed on its budget."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("PhaseDeadlineSet", "v1")
class PhaseDeadlineSetEvent(DomainEvent):
    """A phase's clock started, and this is when its budget runs out (#1546).

    Recorded at the moment the agent's clock starts, from the same reading
    that sets ``SYN_PHASE_DEADLINE`` in the agent's environment, so what an
    operator is shown and what the agent is told are one value rather than
    two derivations of it. ``PhaseStarted.started_at`` plus the budget is NOT
    this time: the phase starts before its workspace is provisioned and the
    clock only after, so that sum is early by however long provisioning took.

    Each attempt at a phase - a retry included - records its own, because
    each one runs on a fresh clock.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    #: When the phase is killed, in UTC.
    deadline: datetime
    #: The whole budget the clock started with, in seconds.
    timeout_seconds: int
