"""PhaseCompleted event - emitted when a phase completes execution."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic
from typing import Any

from event_sourcing import DomainEvent, event


@event("PhaseCompleted", "v1")
class PhaseCompletedEvent(DomainEvent):
    """Event emitted when a phase completes execution.

    Contains the results of the phase including artifact and metrics.
    Cost is Lane 2 telemetry — see execution_cost / session_cost projections.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    completed_at: datetime

    # Outcome
    success: bool
    error_message: str | None = None

    # Results
    artifact_id: str | None = None
    session_id: str | None = None

    # Metrics (tokens only — cost lives in Lane 2)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0

    # Additional metadata
    metadata: dict[str, Any] | None = None
