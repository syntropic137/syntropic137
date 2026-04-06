"""WorkspaceError event - workspace operation failed."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from event_sourcing import DomainEvent, event


@event("WorkspaceError", "v1")
class WorkspaceErrorEvent(DomainEvent):
    """Event emitted when a workspace operation fails.

    Captures error details for debugging and monitoring.
    """

    # Workspace identity
    workspace_id: str
    session_id: str

    # Error info
    operation: str  # create, execute, destroy
    error_type: str
    error_message: str

    # Timing
    occurred_at: datetime

    # Context
    isolation_backend: str | None = None
    metadata: dict[str, Any] = {}
