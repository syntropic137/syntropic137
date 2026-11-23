"""A workspace kept because its work could not be proven safe, as the execution records it (#2321).

Kept beside the aggregate, which is at its size limit, rather than in it.

`RetainedReason` lives here, not in the guard's slice, because the event that
carries it is a domain fact: the guard decides, the execution remembers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        RecordWorkspaceRetainedCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.PhaseWorkspaceRetainedEvent import (
        PhaseWorkspaceRetainedEvent,
    )


class RetainedReason(StrEnum):
    """Why a stale workspace directory was kept (#1983). Kept is not failed.

    Each names the one proof that could not be made. /health counts them, so
    an operator sees what the disk is holding and why, not one opaque number.
    """

    #: No owner, or more than one: nothing says whose work it is.
    UNOWNED = "unowned"
    #: The owning Execution is not terminal, has no record, or ended under
    #: the settle period ago.
    NOT_TERMINAL = "not_terminal"
    #: A container in any state, of any name, binds the directory or below it.
    MOUNTED = "mounted"
    #: Some part of the directory, or of a repository in it, could not be read.
    UNREADABLE = "unreadable"
    #: A repository has a change its HEAD does not hold.
    DIRTY = "dirty"
    #: A file no repository can reproduce, outside every proven cache.
    UNVERSIONED = "unversioned"
    #: A repository holds a stash.
    STASH = "stash"
    #: A commit could not be shown on the remote the Execution names.
    UNPUSHED_UNPROVEN = "unpushed_unproven"
    #: A repository's git directory holds submodule stores (``modules/``),
    #: which nothing here proves pushed: a deinitialized submodule's objects
    #: live there and nowhere else.
    SUBMODULE_STORE_UNPROVEN = "submodule_store_unproven"
    #: The object store holds an object no ref reaches: a blob staged and reset
    #: away, a dropped commit. Its content may exist nowhere else.
    UNREACHABLE_OBJECTS = "unreachable_objects"
    #: Session capture may still be inside the directory.
    CAPTURE_UNKNOWN = "capture_unknown"
    #: The directory was replaced or moved between the check and the delete.
    IDENTITY_CHANGED = "identity_changed"
    #: Every proof held, and the delete itself failed.
    DELETE_FAILED = "delete_failed"


#: The reasons that say the work itself is unproven, so the directory may be
#: its last copy. The rest are eligibility or race outcomes - not yet, still
#: bound, moved under us - and say nothing about the work.
WORK_UNPROVEN: Final = frozenset(
    {
        RetainedReason.UNREADABLE,
        RetainedReason.DIRTY,
        RetainedReason.UNVERSIONED,
        RetainedReason.STASH,
        RetainedReason.UNPUSHED_UNPROVEN,
        RetainedReason.SUBMODULE_STORE_UNPROVEN,
        RetainedReason.UNREACHABLE_OBJECTS,
    }
)


def retained_event(
    command: RecordWorkspaceRetainedCommand, workflow_id: str, phase_id: str | None
) -> PhaseWorkspaceRetainedEvent:
    """The `PhaseWorkspaceRetained` recording ``command``'s kept workspace.

    Payload only: whether it is new to this run is the handler's guard.
    """
    # Deferred: the event imports `RetainedReason` from this module.
    from syn_domain.contexts.orchestration.domain.events.PhaseWorkspaceRetainedEvent import (
        PhaseWorkspaceRetainedEvent,
    )

    return PhaseWorkspaceRetainedEvent(
        workflow_id=workflow_id,
        execution_id=command.aggregate_id,
        phase_id=phase_id,
        workspace_handle=command.workspace_handle,
        reason=command.reason,
        detail=command.detail,
        retained_at=datetime.now(UTC),
    )
