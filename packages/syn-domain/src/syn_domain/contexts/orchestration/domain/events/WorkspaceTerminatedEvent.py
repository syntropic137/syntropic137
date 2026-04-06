"""WorkspaceTerminatedEvent - workspace has been terminated."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event


@event("WorkspaceTerminated", "v1")
class WorkspaceTerminatedEvent(DomainEvent):
    """Event emitted when workspace is terminated.

    Records termination for audit trail and metrics.
    """

    # Workspace identity
    workspace_id: str

    # Termination details
    reason: str  # completed, failed, timeout, cancelled, error

    # Final stats
    total_commands: int
    total_duration_seconds: float

    # Timing
    terminated_at: datetime
