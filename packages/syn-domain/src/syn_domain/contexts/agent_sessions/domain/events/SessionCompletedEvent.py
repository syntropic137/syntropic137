"""SessionCompleted event - represents the fact that a session was completed."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event

from syn_domain.contexts.agent_sessions._shared.value_objects import (
    AgentLaunch,
    SessionStatus,
)


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

    # Whether an agent process ever started for this session.
    #
    # This event is the one place the fact becomes durable, because it is
    # written on every path a session can end by, and the aggregate knows the
    # answer by the time it is written. Recording it here also makes the
    # cutover free: events appended before this field existed simply do not
    # carry it, and a missing value reads back as UNKNOWN - the honest answer
    # for a stream that could not have recorded a launch. No upcaster, no
    # deployment position, no rule about which sessions are "old" (#1047, #1065).
    agent_launch: AgentLaunch = AgentLaunch.UNKNOWN
