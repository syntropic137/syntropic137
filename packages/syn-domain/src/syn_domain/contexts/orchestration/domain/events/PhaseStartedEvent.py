"""PhaseStarted event - emitted when a phase begins execution."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event


@event("PhaseStarted", "v1")
class PhaseStartedEvent(DomainEvent):
    """Event emitted when a phase starts execution.

    Contains context about the phase and its position in the workflow.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    phase_name: str
    phase_order: int
    started_at: datetime
    session_id: str | None = None  # Agent session for this phase
