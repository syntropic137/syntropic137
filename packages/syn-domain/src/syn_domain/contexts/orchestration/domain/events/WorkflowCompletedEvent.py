"""WorkflowCompleted event - emitted when workflow execution completes successfully."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("WorkflowCompleted", "v1")
class WorkflowCompletedEvent(DomainEvent):
    """Event emitted when workflow execution completes successfully.

    Contains summary metrics for the entire workflow execution.
    Cost is Lane 2 telemetry — see execution_cost projection.
    """

    workflow_id: str
    execution_id: str
    completed_at: datetime

    # Summary metrics (tokens only — cost lives in Lane 2)
    total_phases: int
    completed_phases: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_tokens: int
    total_duration_seconds: float

    # Artifact IDs produced
    artifact_ids: list[str]
