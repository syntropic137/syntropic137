"""WorkspaceCreated event - workspace is ready for use."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Any

from event_sourcing import DomainEvent, event


@event("WorkspaceCreated", "v1")
class WorkspaceCreatedEvent(DomainEvent):
    """Event emitted when workspace is ready for agent execution.

    Captures creation timing for performance monitoring.
    """

    # Workspace identity
    workspace_id: str
    session_id: str

    # Context linking
    workflow_id: str | None = None
    execution_id: str | None = None
    phase_id: str | None = None

    # Isolation info
    isolation_backend: str
    container_id: str | None = None

    # Timing
    created_at: datetime
    create_duration_ms: float  # Time to provision workspace

    # Resource info
    workspace_path: str | None = None
    security_settings: dict[str, Any] = {}  # noqa: RUF012

    # The image reference the host resolved and pulled for this workspace,
    # normally digest-pinned (``ghcr.io/...@sha256:...``). Recorded here rather
    # than read back from the container because the host both CHOOSES and pulls
    # it, so there is no window in which the recorded value and the running
    # image can disagree (#1004). Distinct from IsolationStartedEvent's
    # image_manifest, which is build provenance read out of the container and is
    # best-effort. None only for events written before this field existed.
    workspace_image: str | None = None
