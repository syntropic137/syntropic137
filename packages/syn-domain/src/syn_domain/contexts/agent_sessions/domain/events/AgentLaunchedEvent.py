"""AgentLaunched event - represents the fact that a session's agent process launched."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event


@event("AgentLaunched", "v1")
class AgentLaunchedEvent(DomainEvent):
    """Event emitted when a session's agent process is actually launched.

    This is the sole Lane-1 fact that distinguishes "no agent ever ran"
    from "an agent ran and later failed" - both leave zero recorded
    tokens on the failure path, so token counts cannot make that call
    (#1047, #1065). Sessions with no ``AgentLaunched`` event never had
    their agent process started, regardless of how they ended.
    """

    session_id: str
    launched_at: datetime
