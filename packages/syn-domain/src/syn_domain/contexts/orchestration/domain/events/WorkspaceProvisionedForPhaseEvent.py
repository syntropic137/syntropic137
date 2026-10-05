"""WorkspaceProvisionedForPhase event - workspace is ready for a phase."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    SourceCommit,  # noqa: TC001 - needed at runtime for Pydantic
)


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

    #: Where each pinned repository was actually checked out, read back off the
    #: workspace and verified against its pin before the agent was given it
    #: (#967). The run's starting state as it was, not as it was requested.
    #: None on events written before it existed, and on a phase that cloned no
    #: pinned repository.
    checked_out_commits: list[SourceCommit] | None = None
