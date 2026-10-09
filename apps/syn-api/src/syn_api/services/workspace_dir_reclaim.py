"""Reclaim workspace directories nothing will ever come back for (PC-130).

#1560's reclaim runs once, at startup, over RUNNING containers. Every way a
directory outlives its container falls outside it: an OOM-killed container is
exited, so `docker ps` never lists it; a reap that reports a failure keeps
every directory, and at the next startup their containers are gone; a teardown
whose upload hook raised keeps its directory by design and nothing revisits
it. On 2026-10-08 that was twelve directories and 45 GB, and the VPS at 98%.

So this runs on a clock, live only, over the directories themselves. A
directory is a candidate only when all three hold:

* no RUNNING container mounts it - any one of them, however many mount it
  (a stopped one does not protect it - that is the OOM case - but its labels
  still name the execution);
* the execution that owns it is not running. Provisioning events retain the
  owner after its container disappears. A directory with no recorded owner
  waits while any execution runs, and unidentified authored work is retained;
* nothing inside it has changed for the grace period.

A candidate is then guarded (`guard_stale_workspace_dir`). After the guard's
archival - which can take minutes - the directory is first CLAIMED: renamed
out of its workspace path, atomically, so nothing can take it from then on.
Only then is all of the above read again, with the clock still live, and its
repositories compared with what they held before the guard (a commit, stash
or edit made during archival is in no archive). Any difference puts the
directory back; otherwise the claimed directory is deleted. Any doubt about the
inputs - docker unreadable, the execution list unreadable - skips the whole
pass, because "I could not look" must never read as "nothing is running".
So does a rebuild of either read model a pass trusts - the execution list or
the ownership links - which empties it while the coordinator stays live.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_adapters.workspace_backends.stale_dirs import (
        WorkspaceContainer,
        WorkspaceDirListing,
    )
    from syn_domain.contexts.orchestration import (
        HostWorkspaceGit,
        PatchArchive,
        StaleWorkspaceDir,
        WorkspaceDirRemover,
    )

logger = logging.getLogger(__name__)

#: Upper bound on running executions read per pass; matches the reconcile's.
_MAX_RUNNING_EXECUTIONS = 500


@dataclass(frozen=True)
class ReclaimPass:
    """What one pass did. ``skipped`` names why it did not look at all."""

    reclaimed: tuple[str, ...] = ()
    reclaimed_bytes: int = 0
    kept: tuple[str, ...] = ()
    skipped: str | None = None


@dataclass(frozen=True)
class _WorkspaceSnapshot:
    repositories: tuple[tuple[str, int, str], ...]
    unversioned_digest: str


@dataclass
class WorkspaceDirReclaimer:
    """One reclaim pass over the workspace base directory, with its collaborators."""

    base_dir: str
    grace_seconds: float
    list_containers: Callable[[], Awaitable[list[WorkspaceContainer]]]
    running_execution_ids: Callable[[], Awaitable[set[str]]]
    scan_dirs: Callable[[str], list[WorkspaceDirListing]]
    git: HostWorkspaceGit
    archive: PatchArchive
    remover: WorkspaceDirRemover
    clock: Callable[[], float] = field(default=time.time)
    #: Whether side effects may run now; read again just before each deletion.
    is_live: Callable[[], bool] = field(default=lambda: True)
    #: Rename a directory out of its workspace path; return where (blocking).
    claim: Callable[[str], str] = field(default=lambda host_dir: _claim(host_dir))
    #: Put a claimed directory back at its workspace path (blocking).
    release: Callable[[str], None] = field(default=lambda claimed: _release(claimed))
    #: Durable provisioning links survive the removal of Docker labels.
    workspace_owners: Callable[[str], Awaitable[set[str]]] | None = None
    #: Why the read models this pass trusts may be incomplete, or None when
    #: they are known whole. A rebuild clears them while `is_live` stays true.
    read_models_rebuilding: Callable[[], Awaitable[str | None]] = field(
        default=lambda: _known_whole()
    )

    async def _observe(
        self,
    ) -> tuple[dict[str, list[WorkspaceContainer]], set[str], list[WorkspaceDirListing]]:
        containers: dict[str, list[WorkspaceContainer]] = {}
        for container in await self.list_containers():
            containers.setdefault(container.workspace_id, []).append(container)
        running = await self.running_execution_ids()
        listings = await asyncio.to_thread(self.scan_dirs, self.base_dir)
        if self.workspace_owners is not None:
            from syn_adapters.workspace_backends.stale_dirs import WorkspaceContainer

            for listing in listings:
                for owner in await self.workspace_owners(listing.workspace_id):
                    containers.setdefault(listing.workspace_id, []).append(
                        WorkspaceContainer(listing.workspace_id, owner, running=False)
                    )
        return containers, running, listings

    async def run_once(self) -> ReclaimPass:
        """Guard and reclaim every stale directory. Never raises."""
        try:
            rebuilding = await self.read_models_rebuilding()
            if rebuilding is not None:
                logger.info("Workspace reclaim pass skipped: %s", rebuilding)
                return ReclaimPass(skipped=rebuilding)
            containers, running, listings = await self._observe()
        except Exception as exc:
            logger.warning("Skipping workspace reclaim pass: %s", exc, exc_info=True)
            return ReclaimPass(skipped=f"{type(exc).__name__}: {exc}")

        now = self.clock()
        reclaimed: list[str] = []
        kept: list[str] = []
        reclaimed_bytes = 0
        for listing in listings:
            stale = self._stale(listing, containers, running, now)
            if stale is None:
                continue
            if await self._reclaim(stale):
                reclaimed.append(stale.workspace_id)
                reclaimed_bytes += stale.size_bytes
            else:
                kept.append(stale.workspace_id)
        if reclaimed or kept:
            logger.warning(
                "Workspace reclaim pass: reclaimed %d directory(ies), %d bytes; kept %d: %s",
                len(reclaimed),
                reclaimed_bytes,
                len(kept),
                kept,
            )
        return ReclaimPass(
            reclaimed=tuple(reclaimed), reclaimed_bytes=reclaimed_bytes, kept=tuple(kept)
        )

    def _stale(
        self,
        listing: WorkspaceDirListing,
        containers: dict[str, list[WorkspaceContainer]],
        running: set[str],
        now: float,
    ) -> StaleWorkspaceDir | None:
        """The listing as a reclaim candidate, or None while anything may still own it."""
        from syn_domain.contexts.orchestration import StaleWorkspaceDir

        mounts = containers.get(listing.workspace_id, [])
        if any(c.running for c in mounts):
            return None
        owners = {c.execution_id for c in mounts if c.execution_id is not None}
        if owners & running:
            return None
        if not owners and running:
            # Unknown owner: it may be any of the running executions.
            return None
        if len(owners) > 1:
            # Two executions claim it; the archive cannot be linked to one.
            return None
        execution_id = next(iter(owners), None)
        if now - listing.last_modified < self.grace_seconds:
            return None
        return StaleWorkspaceDir(
            host_dir=listing.host_dir,
            workspace_id=listing.workspace_id,
            execution_id=execution_id,
            size_bytes=listing.size_bytes,
            last_modified=listing.last_modified,
        )

    async def _reclaim(self, stale: StaleWorkspaceDir) -> bool:
        """Guard, claim, look again, then delete. Whether the directory is gone.

        ``stale.host_dir`` is already claimed when a pass died holding it, so
        every way of keeping the directory puts it back (`_keep`).
        """
        from syn_domain.contexts.orchestration import (
            guard_stale_workspace_dir,
            remove_reclaimed_dir,
        )

        try:
            before = await self._git_state(stale.host_dir)
        except Exception as exc:
            return await self._keep(stale.host_dir, str(exc))
        reclaimable = await guard_stale_workspace_dir(stale, self.git, self.archive)
        if reclaimable is None:
            return await self._keep(stale.host_dir, "the guard refused it")
        try:
            claimed = await asyncio.to_thread(self.claim, stale.host_dir)
        except OSError as exc:
            return await self._keep(stale.host_dir, f"could not claim it ({exc})")
        why = await self._why_not_still_stale(stale, claimed, before)
        if why is not None:
            return await self._keep(claimed, why)
        return await asyncio.to_thread(remove_reclaimed_dir, reclaimable, self.remover, at=claimed)

    async def _keep(self, path: str, why: str) -> bool:
        """Keep the directory at ``path``, back at its workspace path if claimed. False."""
        logger.warning("Keeping workspace directory %s: %s", path, why)
        try:
            await asyncio.to_thread(self.release, path)
        except OSError:
            logger.exception(
                "Claimed workspace directory %s could not be put back; it stays where it is", path
            )
        return False

    async def _git_state(self, host_dir: str) -> _WorkspaceSnapshot:
        """Repository state and unversioned contents, independent of the workspace path.

        Read before the guard and again under the claim: anything authored in
        git meanwhile (a commit, a stash, a ref, a staged edit) changes it.
        Unversioned bytes are compared too: timestamp-preserving copies must
        not slip past the final check.
        """
        state: list[tuple[str, int, str]] = []
        repos = await self.git.repositories(host_dir)
        for repo in repos:
            digest = hashlib.sha256(await self.git.uncommitted_patch(repo)).hexdigest()
            unpushed = await self.git.unpushed_commits(repo)
            state.append((os.path.relpath(repo, host_dir), unpushed, digest))
        files = await self.git.unversioned_files(host_dir, repos)
        # The gzip header includes the archive time; compare the tar's file
        # contents and metadata, not the time it was compressed.
        digest = hashlib.sha256(gzip.decompress(files) if files else b"").hexdigest()
        return _WorkspaceSnapshot(tuple(sorted(state)), digest)

    async def _why_not_still_stale(
        self, stale: StaleWorkspaceDir, claimed: str, before: _WorkspaceSnapshot
    ) -> str | None:
        """Read everything again under the claim; any change is a reason to keep it."""
        catching_up = "subscriptions began catching up during archival"
        if not self.is_live():
            return catching_up
        try:
            containers, running, listings = await self._observe()
            after = await self._git_state(claimed)
            rebuilding = await self.read_models_rebuilding()
        except Exception as exc:
            return f"could not look again ({type(exc).__name__}: {exc})"
        if rebuilding is not None:
            return f"read models began rebuilding during archival: {rebuilding}"
        listing = next((x for x in listings if x.host_dir == claimed), None)
        if listing is None:
            return "it is no longer listed"
        fresh = self._stale(listing, containers, running, self.clock())
        if fresh is None or fresh.execution_id != stale.execution_id:
            return "a container or running execution claimed it during archival"
        if listing.last_modified > stale.last_modified:
            return "it changed during archival"
        if after != before:
            return "its repositories changed during archival"
        return None if self.is_live() else catching_up


def _claim(host_dir: str) -> str:
    from syn_adapters.workspace_backends.stale_dirs import claim_workspace_dir

    return claim_workspace_dir(host_dir)


def _release(claimed: str) -> None:
    from syn_adapters.workspace_backends.stale_dirs import release_workspace_dir

    release_workspace_dir(claimed)


async def _known_whole() -> str | None:
    return None


async def _reclaim_inputs_rebuilding() -> str | None:
    """Whether the execution list or the ownership links are being rebuilt."""
    from syn_api.services.read_model_status import read_models_rebuilding
    from syn_domain.contexts.orchestration._shared.execution_list_reads import (
        WORKFLOW_EXECUTIONS,
    )
    from syn_domain.contexts.orchestration.slices.workspace_ownership.projection import (
        WorkspaceOwnershipProjection,
    )

    return await read_models_rebuilding(
        {WORKFLOW_EXECUTIONS, WorkspaceOwnershipProjection.PROJECTION_NAME}
    )


async def _running_execution_ids() -> set[str]:
    from syn_api._wiring import get_projection_mgr
    from syn_domain.contexts.orchestration import ExecutionStatus

    rows = await get_projection_mgr().workflow_execution_list.get_all(
        limit=_MAX_RUNNING_EXECUTIONS, status_filter=ExecutionStatus.RUNNING
    )
    if len(rows) >= _MAX_RUNNING_EXECUTIONS:
        # A truncated list could omit an owner; refuse rather than guess.
        raise RuntimeError(f"{len(rows)} running executions; the list may be truncated")
    return {row.workflow_execution_id for row in rows}


def default_reclaimer(is_live: Callable[[], bool]) -> WorkspaceDirReclaimer:
    """The production wiring: docker, the execution projection, host git, MinIO."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.workspace_backends.orphaned import (
        ShutilWorkspaceDirRemover,
        workspace_base_dir,
    )
    from syn_adapters.workspace_backends.stale_dirs import (
        ArtifactStoragePatchArchive,
        SubprocessHostWorkspaceGit,
        list_workspace_containers,
        scan_workspace_dirs,
    )
    from syn_domain.contexts.orchestration.slices.workspace_ownership.projection import (
        WorkspaceOwnershipProjection,
    )
    from syn_shared.settings import get_settings

    return WorkspaceDirReclaimer(
        base_dir=workspace_base_dir(),
        grace_seconds=get_settings().disk.reclaim_grace_hours * 3600,
        list_containers=list_workspace_containers,
        running_execution_ids=_running_execution_ids,
        scan_dirs=scan_workspace_dirs,
        git=SubprocessHostWorkspaceGit(),
        archive=ArtifactStoragePatchArchive(),
        remover=ShutilWorkspaceDirRemover(),
        is_live=is_live,
        workspace_owners=WorkspaceOwnershipProjection(get_projection_store()).owners,
        read_models_rebuilding=_reclaim_inputs_rebuilding,
    )


async def reclaim_on_a_clock(
    reclaimer: WorkspaceDirReclaimer, *, is_live: Callable[[], bool], interval_seconds: float
) -> None:
    """Run a pass every ``interval_seconds``, but only while ``is_live()``.

    Live only: during catch-up the execution list is still being rebuilt, and
    an execution it has not replayed yet would read as not running.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        if not is_live():
            logger.info("Workspace reclaim pass skipped: subscriptions are catching up")
            continue
        await reclaimer.run_once()


_reclaim_task: asyncio.Task[None] | None = None


def start_workspace_reclaim(is_live: Callable[[], bool]) -> None:
    """Start the clock, once. Called after subscriptions are live."""
    global _reclaim_task
    if _reclaim_task is not None and not _reclaim_task.done():
        return
    from syn_shared.settings import get_settings

    _reclaim_task = asyncio.create_task(
        reclaim_on_a_clock(
            default_reclaimer(is_live),
            is_live=is_live,
            interval_seconds=get_settings().disk.reclaim_interval_minutes * 60,
        ),
        name="workspace-dir-reclaim",
    )


async def stop_workspace_reclaim() -> None:
    """Stop the clock; a no-op if never started."""
    global _reclaim_task
    task, _reclaim_task = _reclaim_task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
