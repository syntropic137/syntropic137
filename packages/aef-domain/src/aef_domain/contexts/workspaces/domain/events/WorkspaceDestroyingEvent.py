"""WorkspaceDestroying event - workspace cleanup initiated."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from event_sourcing import DomainEvent, event


@event("WorkspaceDestroying", "v1")
class WorkspaceDestroyingEvent(DomainEvent):
    """Event emitted when workspace destruction begins.

    Tracks the start of cleanup for timing metrics.
    """

    # Workspace identity
    workspace_id: str
    session_id: str

    # Timing
    started_at: datetime
