"""CommandFailedEvent - command execution failed."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event


@event("CommandFailed", "v1")
class CommandFailedEvent(DomainEvent):
    """Event emitted when a command execution fails.

    Records failure details for debugging and monitoring.
    """

    # Workspace identity
    workspace_id: str

    # Command info
    command: list[str]

    # Failure details
    exit_code: int
    error_message: str
    duration_ms: float
    timed_out: bool = False

    # Timing
    failed_at: datetime
