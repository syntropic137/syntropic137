"""AgentExecutionCompleted event - agent finished executing in workspace."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("AgentExecutionCompleted", "v1")
class AgentExecutionCompletedEvent(DomainEvent):
    """Event emitted when the agent has finished executing in a workspace.

    Captures the fact that execution completed and basic metrics.
    Output content is in the observability lane, not here.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    session_id: str | None
    completed_at: datetime
    exit_code: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
