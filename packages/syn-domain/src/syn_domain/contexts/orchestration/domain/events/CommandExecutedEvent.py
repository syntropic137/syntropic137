"""CommandExecutedEvent - command execution succeeded."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event


@event("CommandExecuted", "v1")
class CommandExecutedEvent(DomainEvent):
    """Event emitted when a command executes successfully.

    Records command execution for observability and audit trail.
    """

    # Workspace identity
    workspace_id: str

    # Command info
    command: list[str]

    # Result
    exit_code: int
    success: bool
    duration_ms: float

    # Output stats (content not stored - too large)
    stdout_lines: int = 0
    stderr_lines: int = 0

    # Timing
    executed_at: datetime
