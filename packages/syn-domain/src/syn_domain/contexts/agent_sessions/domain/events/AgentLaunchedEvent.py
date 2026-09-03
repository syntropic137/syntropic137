"""AgentLaunched event - represents the fact that a session's agent process launched."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event


@event("AgentLaunched", "v1")
class AgentLaunchedEvent(DomainEvent):
    """Event emitted once an agent process is observed running for a session.

    Carries the launch fact for a session that is still in flight, so it is
    visible before the session ends and survives a reload of the aggregate.
    The durable answer a reader consumes is on ``SessionCompletedEvent``,
    which the aggregate stamps from this fact on every path a session can
    end by (#1047, #1065).

    Absence of this event in a stream is NOT by itself evidence that no
    agent ran: streams written before this event existed cannot contain it.
    Only the aggregate, which has replayed a whole stream it also wrote, may
    read absence as a negative.
    """

    session_id: str
    launched_at: datetime
