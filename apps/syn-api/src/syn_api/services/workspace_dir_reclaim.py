"""Reclaim workspace directories nothing will ever come back for (PC-130).

#1560's reclaim runs once, at startup, over RUNNING containers. Every way a
directory outlives its container falls outside it: an OOM-killed container is
exited, so `docker ps` never lists it; a reap that reports a failure keeps
every directory, and at the next startup their containers are gone; a teardown
whose upload hook raised keeps its directory by design and nothing revisits
it. On 2026-10-08 that was twelve directories and 45 GB, and the VPS at 98%.

So this runs on a clock, live only, over the directories themselves. A
directory is a candidate only when all three hold:

* no RUNNING container mounts it (a stopped one does not protect it - that
  is the OOM case - but its labels still name the execution);
* the execution that owns it, when known, is not running;
* nothing inside it has changed for the grace period.

A candidate is then guarded (`guard_stale_workspace_dir`) and deleted only on
a clean verdict. Any doubt about the inputs - docker unreadable, the execution
list unreadable - skips the whole pass, because "I could not look" must never
read as "nothing is running".
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.stale_dirs import (
        WorkspaceContainer,
        WorkspaceDirListing,
    )
    from syn_domain.contexts.orchestration import (
        HostWorkspaceGit,
        PatchArchive,
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

    async def run_once(self) -> ReclaimPass:
        """Guard and reclaim every stale directory. Never raises."""
        from syn_domain.contexts.orchestration import (
            StaleWorkspaceDir,
            guard_stale_workspace_dir,
            remove_reclaimed_dir,
        )

        try:
            containers = {c.workspace_id: c for c in await self.list_containers()}
            running = await self.running_execution_ids()
            listings = await asyncio.to_thread(self.scan_dirs, self.base_dir)
        except Exception as exc:
            logger.warning("Skipping workspace reclaim pass: %s", exc, exc_info=True)
            return ReclaimPass(skipped=f"{type(exc).__name__}: {exc}")

        now = self.clock()
        reclaimed: list[str] = []
        kept: list[str] = []
        reclaimed_bytes = 0
        for listing in listings:
            container = containers.get(listing.workspace_id)
            if container is not None and container.running:
                continue
            execution_id = container.execution_id if container is not None else None
            if execution_id is not None and execution_id in running:
                continue
            if now - listing.last_modified < self.grace_seconds:
                continue
            stale = StaleWorkspaceDir(
                host_dir=listing.host_dir,
                workspace_id=listing.workspace_id,
                execution_id=execution_id,
                size_bytes=listing.size_bytes,
            )
            reclaimable = await guard_stale_workspace_dir(stale, self.git, self.archive)
            removed = reclaimable is not None and await asyncio.to_thread(
                remove_reclaimed_dir, reclaimable, self.remover
            )
            if removed:
                reclaimed.append(listing.workspace_id)
                reclaimed_bytes += listing.size_bytes
            else:
                kept.append(listing.workspace_id)
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


def default_reclaimer() -> WorkspaceDirReclaimer:
    """The production wiring: docker, the execution projection, host git, MinIO."""
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
            default_reclaimer(),
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
