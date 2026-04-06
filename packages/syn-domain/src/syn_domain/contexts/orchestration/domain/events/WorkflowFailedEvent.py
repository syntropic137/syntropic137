"""WorkflowFailed event - emitted when workflow execution fails."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from event_sourcing import DomainEvent, event


@event("WorkflowFailed", "v1")
class WorkflowFailedEvent(DomainEvent):
    """Event emitted when workflow execution fails.

    Contains information about the failure and any partial progress.
    """

    workflow_id: str
    execution_id: str
    failed_at: datetime

    # Failure information
    failed_phase_id: str | None = None
    error_message: str
    error_type: str | None = None

    # Partial progress
    completed_phases: int
    total_phases: int

    # Partial metrics (from completed phases)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
