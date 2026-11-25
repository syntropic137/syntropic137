"""A workspace kept because its work could not be proven safe, as the execution records it (#2321).

Kept beside the aggregate, which is at its size limit, rather than in it. The
reasons themselves are value objects in `WorkspaceRetentionValueObjects`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.events.PhaseWorkspaceRetainedEvent import (
    PhaseWorkspaceRetainedEvent,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        RecordWorkspaceRetainedCommand,
    )


def retained_event(
    command: RecordWorkspaceRetainedCommand, workflow_id: str, phase_id: str | None
) -> PhaseWorkspaceRetainedEvent:
    """The `PhaseWorkspaceRetained` recording ``command``'s kept workspace.

    Payload only: whether it is new to this run is the handler's guard.
    """
    return PhaseWorkspaceRetainedEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        phase_id=phase_id,
        workspace_handle=command.workspace_handle,
        reason=command.reason,
        detail=command.detail,
        retained_at=datetime.now(UTC),
    )
