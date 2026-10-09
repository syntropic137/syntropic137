"""Stop a running workspace that outgrows its disk cap, after saving its work (#1805).

`/workspace` is a plain bind mount of a host directory, so nothing stops one
run from filling the disk every other run shares. A hard cap belongs in the
provider (agentic-workspace mounts the directory; a sized loopback volume or
an ext4/XFS project quota on it would be enforced by the kernel). Neither
exists in the pinned provider, and Docker Desktop for Mac supports neither, so
this is the portable floor: measure on a clock, and stop what is over.

A pass measures every workspace directory (`scan_workspace_dirs`, one walk
each). One that is over ``SYN_WORKSPACE_DISK_LIMIT_MB`` AND mounted by a
running container is frozen (`docker pause`, the cgroup freezer), so nothing
in it can write while it is read, and then killed, but only after everything a
teardown would lose is in durable storage, linked to its execution:

* unpushed commits, as a git bundle per repository;
* each repository's uncommitted changes, as a patch;
* every file no repository can reproduce (`artifacts/output` included).

The archive is a snapshot of the frozen state, and the kill is SIGKILL to the
still-frozen container (`docker kill` delivers it, then thaws the cgroup), so
not one more instruction of the agent runs between the snapshot and its death:
no commit or deliverable can be written after it was read (#1805 reverify B1).

Killing the container is what reaches the existing teardown, which deletes
the directory. So when any of that cannot be saved, the container is NOT
killed: it is thawed, the failure is logged and reported, and the run keeps
its work and keeps the disk. A run is never killed with its work unsaved. A
container that cannot be frozen is not touched at all.

The freeze and kill are docker CLI calls on the container agentic-workspace
names, the same seam `docker stop` was; a provider-owned quiesce/snapshot
operation (or a kernel-enforced sized volume) in agentic-workspace would
replace both, and is described in #1805.

Overshoot: a workspace can grow for one interval plus one pass past the cap
before it is stopped. At ``_INTERVAL_SECONDS`` and the write rates seen on the
VPS, that is the margin to leave under the free space the disk pager watches.
Other workspaces are never touched: a pass acts only on directories that are
themselves over the cap.

Live only, like the reclaim clock: during catch-up nothing is acted on.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

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
    )

logger = logging.getLogger(__name__)

#: Seconds between measurements; the bound on how far past the cap a run gets.
_INTERVAL_SECONDS = 60.0

_MB = 1024 * 1024


class UnpushedBundler(Protocol):
    """Reads a repository's unpushed commits as one git bundle."""

    async def unpushed_bundle(self, repo: str) -> bytes:
        """Every commit no remote-tracking ref has, as a bundle. Raises on failure."""
        ...


@dataclass(frozen=True)
class CapPass:
    """What one pass did. ``skipped`` names why it did not look at all."""

    stopped: tuple[str, ...] = ()
    #: Over the cap and running, but its work could not all be saved, so it runs on.
    unpreserved: tuple[str, ...] = ()
    skipped: str | None = None


@dataclass
class WorkspaceDiskCapEnforcer:
    """One pass over the workspace base directory, with its collaborators."""

    base_dir: str
    limit_bytes: int
    list_containers: Callable[[], Awaitable[list[WorkspaceContainer]]]
    scan_dirs: Callable[[str], list[WorkspaceDirListing]]
    git: HostWorkspaceGit
    bundler: UnpushedBundler
    archive: PatchArchive
    freeze_container: Callable[[str], Awaitable[None]]
    thaw_container: Callable[[str], Awaitable[None]]
    stop_container: Callable[[str], Awaitable[None]]
    is_live: Callable[[], bool] = field(default=lambda: True)

    async def run_once(self) -> CapPass:
        """Preserve, then stop, every running workspace over the cap. Never raises."""
        try:
            containers = await self.list_containers()
            listings = await asyncio.to_thread(self.scan_dirs, self.base_dir)
        except Exception as exc:
            logger.warning("Skipping workspace disk-cap pass: %s", exc, exc_info=True)
            return CapPass(skipped=f"{type(exc).__name__}: {exc}")

        running = {c.workspace_id: c for c in containers if c.running}
        stopped: list[str] = []
        unpreserved: list[str] = []
        for listing in listings:
            container = running.get(listing.workspace_id)
            if container is None or listing.size_bytes <= self.limit_bytes:
                continue
            if not self.is_live():
                return CapPass(tuple(stopped), tuple(unpreserved), "catching up")
            if await self._enforce(listing, container.execution_id):
                stopped.append(listing.workspace_id)
            else:
                unpreserved.append(listing.workspace_id)
        return CapPass(stopped=tuple(stopped), unpreserved=tuple(unpreserved))

    async def _enforce(self, listing: WorkspaceDirListing, execution_id: str | None) -> bool:
        """Freeze the workspace, save its work, then kill it. Whether it was killed."""
        from syn_domain.contexts.orchestration import StaleWorkspaceDir

        over = StaleWorkspaceDir(
            host_dir=listing.host_dir,
            workspace_id=listing.workspace_id,
            execution_id=execution_id,
            size_bytes=listing.size_bytes,
            last_modified=listing.last_modified,
        )
        if execution_id is None:
            logger.error(
                "WorkspaceOverDiskCap workspace_id=%s size_bytes=%d limit_bytes=%d: NOT "
                "stopped, no execution owns it, so its work has nowhere to be filed",
                listing.workspace_id,
                listing.size_bytes,
                self.limit_bytes,
            )
            return False
        try:
            await self.freeze_container(listing.workspace_id)
        except Exception as exc:
            logger.error(
                "WorkspaceOverDiskCap workspace_id=%s execution_id=%s: NOT stopped, it "
                "could not be frozen, so its work cannot be read consistently (%s: %s)",
                listing.workspace_id,
                execution_id,
                type(exc).__name__,
                exc,
            )
            return False
        try:
            saved = await self._preserve(over)
        except Exception as exc:
            await self._thaw(listing.workspace_id)
            logger.error(
                "WorkspaceOverDiskCap workspace_id=%s execution_id=%s size_bytes=%d "
                "limit_bytes=%d: NOT stopped, its work could not be saved (%s: %s)",
                listing.workspace_id,
                execution_id or "unknown",
                listing.size_bytes,
                self.limit_bytes,
                type(exc).__name__,
                exc,
            )
            return False
        try:
            await self.stop_container(listing.workspace_id)
        except Exception as exc:
            await self._thaw(listing.workspace_id)
            logger.error(
                "WorkspaceOverDiskCap workspace_id=%s: work saved as %s but stop failed (%s)",
                listing.workspace_id,
                saved,
                exc,
            )
            return False
        logger.error(
            "WorkspaceOverDiskCap workspace_id=%s execution_id=%s size_bytes=%d "
            "limit_bytes=%d: stopped after saving %s",
            listing.workspace_id,
            execution_id,
            listing.size_bytes,
            self.limit_bytes,
            saved,
        )
        return True

    async def _thaw(self, workspace_id: str) -> None:
        """Let a frozen run carry on. A failure is logged: the run stays frozen."""
        try:
            await self.thaw_container(workspace_id)
        except Exception as exc:
            logger.error(
                "WorkspaceOverDiskCap workspace_id=%s: thaw failed, the run is still "
                "frozen; `docker unpause agentic-%s` resumes it (%s: %s)",
                workspace_id,
                workspace_id,
                type(exc).__name__,
                exc,
            )

    async def _preserve(self, over: StaleWorkspaceDir) -> list[str]:
        """Archive everything a teardown would lose. Raises on the first failure."""
        saved: list[str] = []
        repos = await self.git.repositories(over.host_dir)
        for repo in repos:
            if await self.git.unpushed_commits(repo):
                bundle = await self.bundler.unpushed_bundle(repo)
                saved.append(await self.archive.save(over, str(Path(repo) / ".bundle"), bundle))
            patch = await self.git.uncommitted_patch(repo)
            if patch:
                saved.append(await self.archive.save(over, repo, patch))
        files = await self.git.unversioned_files(over.host_dir, repos)
        if files:
            saved.append(await self.archive.save_files(over, files))
        return saved


async def _docker(verb: str, workspace_id: str) -> None:
    """`docker <verb>` the container mounting ``workspace_id``. Raises on failure."""
    # agentic-workspace names a workspace's container "agentic-" + its id.
    proc = await asyncio.create_subprocess_exec(
        "docker",
        verb,
        f"agentic-{workspace_id}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"docker {verb} exited {proc.returncode}: {stderr.decode()[:200]}")


async def _freeze_workspace_container(workspace_id: str) -> None:
    await _docker("pause", workspace_id)


async def _thaw_workspace_container(workspace_id: str) -> None:
    await _docker("unpause", workspace_id)


async def _kill_workspace_container(workspace_id: str) -> None:
    # SIGKILL, not `docker stop`: a grace period would let the agent write
    # after the snapshot. Docker delivers it to the paused container, then thaws.
    await _docker("kill", workspace_id)


def default_enforcer(limit_mb: int, is_live: Callable[[], bool]) -> WorkspaceDiskCapEnforcer:
    """The production wiring: docker, host git, MinIO."""
    from syn_adapters.workspace_backends.orphaned import workspace_base_dir
    from syn_adapters.workspace_backends.stale_dirs import (
        ArtifactStoragePatchArchive,
        SubprocessHostWorkspaceGit,
        list_workspace_containers,
        scan_workspace_dirs,
    )

    git = SubprocessHostWorkspaceGit()
    return WorkspaceDiskCapEnforcer(
        base_dir=workspace_base_dir(),
        limit_bytes=limit_mb * _MB,
        list_containers=list_workspace_containers,
        scan_dirs=scan_workspace_dirs,
        git=git,
        bundler=git,
        archive=ArtifactStoragePatchArchive(),
        freeze_container=_freeze_workspace_container,
        thaw_container=_thaw_workspace_container,
        stop_container=_kill_workspace_container,
        is_live=is_live,
    )


async def enforce_on_a_clock(
    enforcer: WorkspaceDiskCapEnforcer, *, is_live: Callable[[], bool], interval_seconds: float
) -> None:
    """Run a pass every ``interval_seconds``, but only while ``is_live()``."""
    while True:
        await asyncio.sleep(interval_seconds)
        if is_live():
            await enforcer.run_once()


_cap_task: asyncio.Task[None] | None = None


def start_workspace_disk_cap(is_live: Callable[[], bool]) -> None:
    """Start the clock, once. A limit of 0 turns enforcement off."""
    global _cap_task
    if _cap_task is not None and not _cap_task.done():
        return
    from syn_shared.settings.workspace import WorkspaceSettings

    limit_mb = WorkspaceSettings().disk_limit_mb
    if limit_mb == 0:
        logger.warning("SYN_WORKSPACE_DISK_LIMIT_MB=0: workspace disk use is not capped")
        return
    _cap_task = asyncio.create_task(
        enforce_on_a_clock(
            default_enforcer(limit_mb, is_live), is_live=is_live, interval_seconds=_INTERVAL_SECONDS
        ),
        name="workspace-disk-cap",
    )


async def stop_workspace_disk_cap() -> None:
    """Stop the clock; a no-op if never started."""
    global _cap_task
    task, _cap_task = _cap_task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
