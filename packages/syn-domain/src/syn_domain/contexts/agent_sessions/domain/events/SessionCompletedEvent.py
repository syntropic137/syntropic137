"""SessionCompleted event - represents the fact that a session was completed."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event

from syn_domain.contexts.agent_sessions._shared.value_objects import SessionStatus  # noqa: TC001


@event("SessionCompleted", "v1")
class SessionCompletedEvent(DomainEvent):
    """Event emitted when an agent session is completed.

    Lane 1 domain truth — tokens only. Cost is Lane 2 telemetry in session_cost (#695).
    """

    # Context
    session_id: str

    # Outcome
    status: SessionStatus
    completed_at: datetime

    # Final metrics (tokens only — cost lives in Lane 2)
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_tokens: int
    operation_count: int

    # Error (if failed)
    error_message: str | None = None
