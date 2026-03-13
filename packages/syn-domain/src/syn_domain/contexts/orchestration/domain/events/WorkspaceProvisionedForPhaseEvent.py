"""WorkspaceProvisionedForPhase event - workspace is ready for a phase."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


@event("WorkspaceProvisionedForPhase", "v1")
class WorkspaceProvisionedForPhaseEvent(DomainEvent):
    """Event emitted when a workspace has been provisioned for a phase.

    Indicates infrastructure is ready — secrets injected, artifacts staged,
    CLI command built. The processor can now dispatch agent execution.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    workspace_id: str
    session_id: str
    provisioned_at: datetime
