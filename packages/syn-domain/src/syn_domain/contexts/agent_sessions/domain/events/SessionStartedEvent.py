"""SessionStarted event - represents the fact that a session was started."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from event_sourcing import DomainEvent, event


@event("SessionStarted", "v1")
class SessionStartedEvent(DomainEvent):
    """Event emitted when an agent session is started.

    Sessions track agent execution for observability.
    """

    # Session identity
    session_id: str

    # Context
    workflow_id: str
    execution_id: str | None = None  # Links session to a specific workflow execution/run
    phase_id: str
    milestone_id: str | None = None

    # Agent info
    agent_provider: str
    agent_model: str | None = None

    # Timing
    started_at: datetime

    # Metadata
    metadata: dict[str, Any] = {}  # noqa: RUF012
