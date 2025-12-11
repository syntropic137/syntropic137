"""WorkspaceCommandExecuted event - command run in workspace."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from event_sourcing import DomainEvent, event


@event("WorkspaceCommandExecuted", "v1")
class WorkspaceCommandExecutedEvent(DomainEvent):
    """Event emitted when a command is executed in the workspace.

    Tracks command execution for observability.
    """

    # Workspace identity
    workspace_id: str
    session_id: str

    # Command info
    command: list[str]
    working_directory: str | None = None

    # Result
    exit_code: int
    success: bool
    duration_ms: float

    # Output (truncated)
    stdout_lines: int = 0
    stderr_lines: int = 0

    # Timing
    executed_at: datetime

    # Metadata
    metadata: dict[str, Any] = {}  # noqa: RUF012
