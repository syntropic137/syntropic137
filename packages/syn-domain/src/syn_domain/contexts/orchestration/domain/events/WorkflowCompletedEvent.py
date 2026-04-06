"""WorkflowCompleted event - emitted when workflow execution completes successfully."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from event_sourcing import DomainEvent, event


@event("WorkflowCompleted", "v1")
class WorkflowCompletedEvent(DomainEvent):
    """Event emitted when workflow execution completes successfully.

    Contains summary metrics for the entire workflow execution.
    """

    workflow_id: str
    execution_id: str
    completed_at: datetime

    # Summary metrics
    total_phases: int
    completed_phases: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: Decimal
    total_duration_seconds: float

    # Artifact IDs produced
    artifact_ids: list[str]
