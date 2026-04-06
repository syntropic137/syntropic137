"""IsolationStartedEvent - isolation environment is running."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from event_sourcing import DomainEvent, event


@event("IsolationStarted", "v1")
class IsolationStartedEvent(DomainEvent):
    """Event emitted when isolation environment is running.

    Indicates the container/VM/sandbox has been provisioned and is ready.
    """

    # Workspace identity
    workspace_id: str

    # Isolation details
    isolation_id: str  # Container ID, VM ID, etc.
    isolation_type: str  # docker, firecracker, e2b, memory

    # Sidecar proxy (if enabled)
    proxy_url: str | None = None  # e.g., http://localhost:8080

    # Image version manifest (from /opt/agentic/version.json)
    # None for older images or non-Docker backends that don't provide it.
    image_manifest: dict[str, Any] | None = None

    # Timing
    started_at: datetime
