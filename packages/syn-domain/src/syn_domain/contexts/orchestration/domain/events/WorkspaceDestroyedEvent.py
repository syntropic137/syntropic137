"""WorkspaceDestroyed event - workspace fully cleaned up."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event


@event("WorkspaceDestroyed", "v1")
class WorkspaceDestroyedEvent(DomainEvent):
    """Event emitted when workspace is fully destroyed.

    Captures full lifecycle timing for performance monitoring.
    """

    # Workspace identity
    workspace_id: str
    session_id: str

    # Timing
    destroyed_at: datetime
    destroy_duration_ms: float  # Time to cleanup
    total_lifetime_ms: float  # Total time from create to destroy

    # Stats
    commands_executed: int = 0
    artifacts_collected: int = 0
