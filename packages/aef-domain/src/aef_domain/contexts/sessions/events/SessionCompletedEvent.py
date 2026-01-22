"""SessionCompleted event - represents the fact that a session was completed."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from decimal import Decimal  # noqa: TC003

from event_sourcing import DomainEvent, event

from aef_domain.contexts.sessions._shared.value_objects import SessionStatus  # noqa: TC001


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
