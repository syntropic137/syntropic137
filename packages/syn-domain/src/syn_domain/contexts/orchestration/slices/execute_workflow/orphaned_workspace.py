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
It never pushes - the container's credential died with it - and it archives
nothing (#1983 slice 1): a directory may go only when deleting it loses
NOTHING. Every repository is clean, nothing is stashed, nothing lies outside
a repository's history but proven caches, and every commit is shown on the
real remote by `git ls-remote` against the repository the Execution names.
Any doubt is a `Retained` with its `RetainedReason`, never a deletion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
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


@dataclass(frozen=True)
class Retained:
    """A stale directory that stays, and the first proof that failed."""

    reason: RetainedReason
    detail: str


#: The Execution statuses after which nothing will write a workspace again.
TERMINAL_EXECUTION_STATUSES = frozenset({"completed", "failed", "cancelled"})


@dataclass(frozen=True)
class OwnerExecution:
    """What the execution read model says about a directory's owner."""

    execution_id: str
    status: str
    #: Epoch seconds of the terminal event, or None when not terminal or unknown.
    terminal_at: float | None
    #: Remote URLs of the repositories the Execution cloned (ADR-058).
    repositories: tuple[str, ...] = ()


def judge_owner(
    owners: set[str],
    record: OwnerExecution | None,
    *,
    now: float,
    settle_seconds: float,
) -> Retained | None:
    """Whether the directory's one owner is finished and settled; None when it is.

    Eligibility comes from the Execution's terminal event, never from file
    mtimes: an mtime is the agent's to set, the terminal event is not.
    """
    if len(owners) != 1:
        what = "no execution" if not owners else f"{len(owners)} executions"
        return Retained(RetainedReason.UNOWNED, f"{what} own it")
    (owner,) = owners
    if record is None or record.execution_id != owner:
        return Retained(RetainedReason.NOT_TERMINAL, f"{owner} has no execution record")
    if record.status not in TERMINAL_EXECUTION_STATUSES or record.terminal_at is None:
        return Retained(RetainedReason.NOT_TERMINAL, f"{owner} is {record.status}")
    settled_for = now - record.terminal_at
    if settled_for < settle_seconds:
        return Retained(
            RetainedReason.NOT_TERMINAL,
            f"{owner} ended {settled_for:.0f}s ago; settles after {settle_seconds:.0f}s",
        )
    return None


@dataclass(frozen=True)
class StaleWorkspaceDir:
    """A workspace directory whose one owner is terminal and settled.

    ``execution_id`` is None when neither the durable provisioning index nor
    any container label names its owner; the guard keeps such a directory.
    ``remote_urls`` are the repositories the owning Execution names: the only
    remotes a commit may be proven on. The repository's own config is the
    agent's to write, so it never names one.
    """

    host_dir: str
    workspace_id: str
    execution_id: str | None
    size_bytes: int
    remote_urls: tuple[str, ...] = ()


class HostWorkspaceGit(Protocol):
    """Reads a workspace's repositories from the host, without running them.

    Every method raises when it cannot give a definite answer; the guard reads
    any raise as a reason to keep the directory.
    """

    async def repositories(self, host_dir: str) -> list[str]:
        """Every git repository under ``host_dir``, bare ones and submodules included."""
        ...

    async def has_stash(self, repo: str) -> bool:
        """Whether ``refs/stash`` exists."""
        ...

    async def is_dirty(self, repo: str) -> bool:
        """Whether the index or working tree differs from HEAD, untracked files included.

        False for a bare repository.
        """
        ...

    async def unversioned_paths(self, host_dir: str, repos: list[str]) -> list[str]:
        """Every file under ``host_dir`` no repository can reproduce, less proven caches.

        Files outside ``repos`` and files they ignore. Empty when there are none.
        """
        ...

    async def has_submodule_store(self, repo: str) -> bool:
        """Whether the repository's git directory has a non-empty ``modules/``."""
        ...

    async def unreachable_objects(self, repo: str) -> int:
        """Objects of any type (commit, tree, blob, tag) no ref or reflog reaches."""
        ...

    async def unproven_commits(self, repo: str, advertised: frozenset[str]) -> int:
        """Commits reachable from HEAD or a local ref that no ``advertised`` object reaches.

        Remote-tracking refs (``refs/remotes/*``) are not tips and not proof:
        they are local files the agent could write. An advertised object
        missing locally proves nothing.
        """
        ...


class RemoteRefs(Protocol):
    """What a remote advertises, read from the remote itself (``git ls-remote``)."""

    async def advertised(self, url: str) -> frozenset[str]:
        """Every object id ``url`` advertises. Raises when it cannot be read."""
        ...


async def guard_stale_workspace_dir(
    stale: StaleWorkspaceDir, git: HostWorkspaceGit, remotes: RemoteRefs
) -> ReclaimableDir | Retained:
    """Return the directory as reclaimable only if deleting it loses nothing.

    Read-only: nothing is pushed, archived or moved. Never raises; every
    failure is a `Retained` naming the proof that could not be made.
    """
    if stale.execution_id is None:
        return _keep(stale, Retained(RetainedReason.UNOWNED, "no execution owns it"))
    try:
        repos = await git.repositories(stale.host_dir)
        for repo in repos:
            if await git.has_stash(repo):
                return _keep(stale, Retained(RetainedReason.STASH, f"{repo} holds a stash"))
        for repo in repos:
            if await git.is_dirty(repo):
                return _keep(
                    stale, Retained(RetainedReason.DIRTY, f"{repo} has uncommitted changes")
                )
        unversioned = await git.unversioned_paths(stale.host_dir, repos)
        store = await _store_risk(git, repos)
    except Exception as exc:
        return _keep(stale, Retained(RetainedReason.UNREADABLE, _described(exc)))
    if unversioned:
        return _keep(
            stale,
            Retained(
                RetainedReason.UNVERSIONED,
                f"{len(unversioned)} file(s) no repository holds, e.g. {unversioned[0]}",
            ),
        )
    if store is not None:
        return _keep(stale, store)
    unproven = await _unproven(stale, git, remotes, repos)
    if unproven is not None:
        return _keep(stale, unproven)
    return ReclaimableDir(
        host_dir=stale.host_dir, workspace_id=stale.workspace_id, size_bytes=stale.size_bytes
    )


async def _store_risk(git: HostWorkspaceGit, repos: list[str]) -> Retained | None:
    """What an object store may hold that no proof below covers. Fail closed, unproven."""
    for repo in repos:
        if await git.has_submodule_store(repo):
            return Retained(
                RetainedReason.SUBMODULE_STORE_UNPROVEN, f"{repo} holds submodule stores"
            )
        unreachable = await git.unreachable_objects(repo)
        if unreachable:
            return Retained(
                RetainedReason.UNREACHABLE_OBJECTS,
                f"{repo} holds {unreachable} object(s) no ref reaches",
            )
    return None


async def _unproven(
    stale: StaleWorkspaceDir, git: HostWorkspaceGit, remotes: RemoteRefs, repos: list[str]
) -> Retained | None:
    """None when every commit in every repository is shown on a named remote."""
    if not repos:
        return None
    if not stale.remote_urls:
        return Retained(
            RetainedReason.UNPUSHED_UNPROVEN, f"{stale.execution_id} names no repository"
        )
    advertised: set[str] = set()
    try:
        for url in stale.remote_urls:
            advertised |= await remotes.advertised(url)
    except Exception as exc:
        return Retained(RetainedReason.UNPUSHED_UNPROVEN, f"ls-remote: {_described(exc)}")
    try:
        for repo in repos:
            unproven = await git.unproven_commits(repo, frozenset(advertised))
            if unproven:
                return Retained(
                    RetainedReason.UNPUSHED_UNPROVEN,
                    f"{unproven} commit(s) in {repo} are on no named remote",
                )
    except Exception as exc:
        return Retained(RetainedReason.UNPUSHED_UNPROVEN, _described(exc))
    return None


def _described(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _keep(stale: StaleWorkspaceDir, retained: Retained) -> Retained:
    logger.warning(
        "Keeping stale workspace directory %s (execution %s, %d bytes): %s: %s",
        stale.host_dir,
        stale.execution_id or "unknown",
        stale.size_bytes,
        retained.reason.value,
        retained.detail,
    )
    return retained


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
