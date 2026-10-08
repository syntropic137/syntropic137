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

AND WHEN THE CONTAINER IS ALREADY GONE (PC-130). The guard above needs a live
container, and a startup reap only sees running ones. A container that was
OOM-killed, removed by a reap that then reported a failure, or swapped out by
force leaves a directory nobody guards: twelve of them, 45 GB, filled the VPS
on 2026-10-08. `guard_stale_workspace_dir` is the host-side guard for those.
It never pushes - the container's credential died with it - so its rules are
the owner's: any commit not on a remote keeps the directory, and an
uncommitted change is archived as a patch before the directory may go.
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
    #: Bytes on disk when it was guarded; 0 when nobody measured (the startup path).
    size_bytes: int = 0


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


@dataclass(frozen=True)
class StaleWorkspaceDir:
    """A workspace directory with no container left and no running execution.

    ``execution_id`` is None when neither the durable provisioning index nor
    any container label names its owner. Unidentified authored work is kept.
    """

    host_dir: str
    workspace_id: str
    execution_id: str | None
    size_bytes: int
    #: Newest mtime inside when it was found stale; a later one means it changed.
    last_modified: float = 0.0


class HostWorkspaceGit(Protocol):
    """Reads a workspace's repositories from the host, without running them.

    Every method raises when it cannot give a definite answer; the guard reads
    any raise as "at risk" and keeps the directory.
    """

    async def repositories(self, host_dir: str) -> list[str]:
        """Every git repository under ``host_dir``, bare ones and submodules included."""
        ...

    async def unpushed_commits(self, repo: str) -> int:
        """Commits reachable from any ref or HEAD that no remote-tracking ref has."""
        ...

    async def uncommitted_patch(self, repo: str) -> bytes:
        """The working tree's changes against HEAD, untracked files included.

        Empty when the tree is clean, or the repository is bare. Raises when
        one patch cannot hold it (an index that differs from HEAD and tree).
        """
        ...

    async def unversioned_files(self, host_dir: str, repos: list[str]) -> bytes:
        """An archive of every file under ``host_dir`` no repository can reproduce.

        Files outside ``repos`` and files they ignore, less proven caches.
        Empty when there are none.
        """
        ...


class PatchArchive(Protocol):
    """Durable storage for a reclaimed workspace's uncommitted changes."""

    async def save(self, stale: StaleWorkspaceDir, repo: str, patch: bytes) -> str:
        """Store ``patch`` linked to the stale dir's execution; return where. Raises on failure."""
        ...

    async def save_files(self, stale: StaleWorkspaceDir, tarball: bytes) -> str:
        """Store the unversioned-files archive the same way; return where. Raises on failure."""
        ...


async def guard_stale_workspace_dir(
    stale: StaleWorkspaceDir, git: HostWorkspaceGit, archive: PatchArchive
) -> ReclaimableDir | None:
    """Return the directory as reclaimable only if deleting it loses nothing.

    A commit not on any remote keeps it: there is no credential left to push
    with, so the directory is that commit's only copy. Uncommitted changes, and
    every file outside a repository's history, are archived first, and a failed
    archive keeps it. Never raises.
    """
    try:
        repos = await git.repositories(stale.host_dir)
        for repo in repos:
            unpushed = await git.unpushed_commits(repo)
            if unpushed:
                return _keep(stale, f"{unpushed} unpushed commit(s) in {repo}")
        pending = await _unpreserved_work(stale.host_dir, git, repos)
        if pending and stale.execution_id is None:
            return _keep(stale, "its authored work has no known execution owner")
        saved = [await work.save(stale, archive) for work in pending]
    except Exception as exc:
        return _keep(stale, f"its work could not be shown safe ({type(exc).__name__}: {exc})")
    for uri in saved:
        logger.warning(
            "Stale workspace %s (execution %s) had unpreserved work; saved as %s "
            "before its directory was reclaimed",
            stale.workspace_id,
            stale.execution_id or "unknown",
            uri,
        )
    return ReclaimableDir(
        host_dir=stale.host_dir, workspace_id=stale.workspace_id, size_bytes=stale.size_bytes
    )


@dataclass(frozen=True)
class _UncommittedPatch:
    repo: str
    patch: bytes

    async def save(self, stale: StaleWorkspaceDir, archive: PatchArchive) -> str:
        return await archive.save(stale, self.repo, self.patch)


@dataclass(frozen=True)
class _UnversionedFiles:
    tarball: bytes

    async def save(self, stale: StaleWorkspaceDir, archive: PatchArchive) -> str:
        return await archive.save_files(stale, self.tarball)


async def _unpreserved_work(
    host_dir: str, git: HostWorkspaceGit, repos: list[str]
) -> list[_UncommittedPatch | _UnversionedFiles]:
    """Everything deleting ``host_dir`` would lose that no remote holds, unsaved yet.

    Read in full before anything is saved, so the guard can refuse an
    unidentified owner once for all of it rather than once per kind.
    """
    pending: list[_UncommittedPatch | _UnversionedFiles] = []
    for repo in repos:
        patch = await git.uncommitted_patch(repo)
        if patch:
            pending.append(_UncommittedPatch(repo, patch))
    files = await git.unversioned_files(host_dir, repos)
    if files:
        pending.append(_UnversionedFiles(files))
    return pending


def _keep(stale: StaleWorkspaceDir, why: str) -> None:
    logger.error(
        "Keeping stale workspace directory %s (execution %s, %d bytes): %s",
        stale.host_dir,
        stale.execution_id or "unknown",
        stale.size_bytes,
        why,
    )


def remove_reclaimed_dir(
    reclaimable: ReclaimableDir, remover: WorkspaceDirRemover, *, at: str | None = None
) -> bool:
    """Delete a directory the guard cleared. Returns whether it is gone.

    ``at`` is where it is now, when it was moved after the guard (a claimed
    stale directory); the log still names the path it was guarded at.
    The ``WorkspaceReclaimed`` log line is the record of the deletion (PC-130):
    one line per directory, with its size, that an operator can sum.
    """
    try:
        remover.remove(at or reclaimable.host_dir)
    except OSError:
        logger.warning(
            "Could not remove reclaimed workspace directory %s",
            at or reclaimable.host_dir,
            exc_info=True,
        )
        return False
    logger.info(
        "WorkspaceReclaimed workspace_id=%s host_dir=%s size_bytes=%d",
        reclaimable.workspace_id,
        reclaimable.host_dir,
        reclaimable.size_bytes,
    )
    return True


def _anything_at_risk(saved: SavedWork) -> bool:
    """Whether deleting now could lose work: an unfinished walk, or a refused push."""
    return saved.unreadable is not None or any(r.pushed_ref is None for r in saved.quarantined)
