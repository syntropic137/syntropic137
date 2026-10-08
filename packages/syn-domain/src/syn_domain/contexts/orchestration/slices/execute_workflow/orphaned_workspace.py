"""Reclaiming the host directory of a workspace whose process died (#1560).

THE PATH THAT NEVER REACHED TEARDOWN. A phase that completes, fails or is
cancelled runs the unpushed-work guard and then tears its workspace down, and
the teardown deletes the host directory (#1184 pins that order). A workspace
whose owning API process died - OOM, crash, deploy - reaches none of that: the
startup reap removes its container and nothing ever revisits its directory.
Twenty-three such directories filled flywheel's disk until Postgres failed with
ENOSPC mid-run.

THE GUARD STILL COMES FIRST. A directory nobody is coming back for may still
hold the only copy of an agent's commits, and deleting it unguarded is exactly
the loss ``refs/syn/lost/...`` exists to prevent. So reclaiming is two steps
whose order is enforced by type rather than by convention:

* `guard_orphaned_workspace` runs the SAME walk the terminal paths run
  (`save_unpushed_work`) while the orphan's container is still alive, and
  returns a `ReclaimableDir` only if nothing is left at risk - clean, or every
  quarantine push landed;
* `remove_reclaimed_dir` accepts only that value. There is no way to name a
  directory to it that the guard did not clear.

Anything short of a clean verdict keeps the directory: a walk that could not
finish, or a quarantine push that was refused, leaves the files on disk as the
last copy, and the log says where.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    save_unpushed_work,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.errors import SavedWork
    from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_git import (
        GitWorkspace,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrphanedWorkspace:
    """A workspace still on the host whose execution's process is gone.

    ``workspace`` must still answer commands - its container has not been
    reaped yet - because the guard runs inside it, where its repositories are.
    """

    workspace: GitWorkspace
    workspace_id: str
    execution_id: str
    host_dir: str

    @property
    def quarantine_phase(self) -> str:
        """The phase segment of its quarantine ref.

        The container does not record which phase it was running, so the ref
        names the workspace instead: still unique, still under the execution's
        own ``refs/syn/lost/<execution-id>/`` namespace where an operator looks.
        """
        return f"orphaned-{self.workspace_id}"


@dataclass(frozen=True)
class ReclaimableDir:
    """A host directory the guard has cleared for deletion.

    Construct only through `guard_orphaned_workspace`; holding one is the
    proof that the guard ran and found nothing left at risk.
    """

    host_dir: str
    workspace_id: str


class WorkspaceDirRemover(Protocol):
    """Deletes a workspace's host directory. Irreversible."""

    def remove(self, host_dir: str) -> None: ...


async def guard_orphaned_workspace(orphan: OrphanedWorkspace) -> ReclaimableDir | None:
    """Rescue what the orphan holds; return its directory only if nothing is at risk.

    Never raises for a failure: `save_unpushed_work` already turns every one
    into a reported ``unreadable``, and that keeps the directory.
    """
    saved = await save_unpushed_work(
        orphan.workspace,
        execution_id=orphan.execution_id,
        phase_id=orphan.quarantine_phase,
        # Strictest reading: a dirty tree is work. Nobody is left to say
        # otherwise for an orphan.
        delivers_repo_changes=True,
    )
    if _anything_at_risk(saved):
        logger.error(
            "Keeping orphaned workspace directory %s (execution %s): its work could not "
            "all be shown safe, so these files may be the last copy. %s",
            orphan.host_dir,
            orphan.execution_id,
            saved.unreadable or "A quarantine push was refused.",
        )
        return None
    if saved.quarantined:
        logger.warning(
            "Orphaned workspace %s held unpushed work; it was quarantined under "
            "refs/syn/lost/%s/%s before its directory was reclaimed",
            orphan.workspace_id,
            orphan.execution_id,
            orphan.quarantine_phase,
        )
    return ReclaimableDir(host_dir=orphan.host_dir, workspace_id=orphan.workspace_id)


def remove_reclaimed_dir(reclaimable: ReclaimableDir, remover: WorkspaceDirRemover) -> bool:
    """Delete a directory the guard cleared. Returns whether it is gone."""
    try:
        remover.remove(reclaimable.host_dir)
    except OSError:
        logger.warning(
            "Could not remove reclaimed workspace directory %s", reclaimable.host_dir, exc_info=True
        )
        return False
    logger.info("Removed orphaned workspace directory %s", reclaimable.host_dir)
    return True


def _anything_at_risk(saved: SavedWork) -> bool:
    """Whether deleting now could lose work: an unfinished walk, or a refused push."""
    return saved.unreadable is not None or any(r.pushed_ref is None for r in saved.quarantined)
