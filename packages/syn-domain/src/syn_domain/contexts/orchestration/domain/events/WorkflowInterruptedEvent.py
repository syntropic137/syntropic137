"""WorkflowInterrupted event - emitted when workflow execution is forcefully interrupted."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event
from pydantic import Field


@event("WorkflowInterrupted", "v1")
class WorkflowInterruptedEvent(DomainEvent):
    """Event emitted when workflow execution is forcefully interrupted.

    Distinct from ExecutionCancelledEvent (cooperative user cancel) — this event
    is emitted when the engine receives a CANCEL signal mid-streaming and sends
    SIGINT to the Claude CLI process to stop it immediately.

    Contains the git SHA and any partial artifacts collected before interruption.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    interrupted_at: datetime

    # Context
    reason: str | None = None
    git_sha: str | None = None

    # Partial artifacts collected before interruption
    partial_artifact_ids: list[str] = Field(default_factory=list)

    # Partial metrics (tokens consumed up to interrupt point)
    partial_input_tokens: int = 0
    partial_output_tokens: int = 0
