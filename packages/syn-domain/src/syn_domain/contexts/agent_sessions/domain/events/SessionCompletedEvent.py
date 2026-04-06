"""SessionCompleted event - represents the fact that a session was completed."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from event_sourcing import DomainEvent, event

from syn_domain.contexts.agent_sessions._shared.value_objects import SessionStatus


@event("SessionCompleted", "v1")
class SessionCompletedEvent(DomainEvent):
    """Event emitted when an agent session is completed."""

    # Context
    session_id: str

    # Outcome
    status: SessionStatus
    completed_at: datetime

    # Final metrics
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: Decimal
    operation_count: int

    # Error (if failed)
    error_message: str | None = None
