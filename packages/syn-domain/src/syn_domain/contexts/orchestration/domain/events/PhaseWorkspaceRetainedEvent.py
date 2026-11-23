"""PhaseWorkspaceRetained event - a workspace kept because its work is unproven (#2321)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event

from syn_domain.contexts.orchestration.domain.aggregate_execution.workspace_retention import (
    RetainedReason,  # noqa: TC001 - needed at runtime for Pydantic
)


@event("PhaseWorkspaceRetained", "v1")
class PhaseWorkspaceRetainedEvent(DomainEvent):
    """A workspace of this execution was KEPT: the guard could not prove its work safe.

    Written by whichever guard made the keep decision - the orphan guard at
    startup or the stale-directory reclaimer - so the run, not only a log
    line, says where work may still be. Recorded once per workspace and
    reason; a reclaim pass that keeps it again adds nothing.

    ``workspace_handle`` is the workspace id: host-independent, never a path
    or a container id, which are infrastructure and gone after a restart.
    ``phase_id`` is the phase the execution's own stream provisioned that
    workspace for, or None when the stream never named it.
    """

    workflow_id: str
    execution_id: str
    phase_id: str | None = None
    workspace_handle: str
    reason: RetainedReason
    detail: str
    retained_at: datetime
