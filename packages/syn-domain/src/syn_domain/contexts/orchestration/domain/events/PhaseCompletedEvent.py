"""PhaseCompleted event - emitted when a phase completes execution."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from event_sourcing import DomainEvent, event


@event("PhaseCompleted", "v1")
class PhaseCompletedEvent(DomainEvent):
    """Event emitted when a phase completes execution.

    Contains the results of the phase including artifact and metrics.
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

    # Metrics
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    duration_seconds: float = 0.0

    # Additional metadata
    metadata: dict[str, Any] | None = None
