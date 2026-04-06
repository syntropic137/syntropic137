"""WorkspaceCreating event - workspace creation initiated."""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event


@event("WorkspaceCreating", "v1")
class WorkspaceCreatingEvent(DomainEvent):
    """Event emitted when workspace creation begins.

    Tracks the start of workspace provisioning for timing metrics.
    """

    # Workspace identity
    workspace_id: str
    session_id: str

    # Context linking
    workflow_id: str | None = None
    execution_id: str | None = None
    phase_id: str | None = None

    # Isolation info
    isolation_backend: str  # firecracker, gvisor, docker_hardened, cloud, local
    container_image: str | None = None

    # Timing
    started_at: datetime
