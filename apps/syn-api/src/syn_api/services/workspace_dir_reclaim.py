"""Reclaim workspace directories nothing will ever come back for (PC-130, #1983).

#1560's reclaim runs once, at startup, over RUNNING containers. Every way a
directory outlives its container falls outside it: an OOM-killed container,
a reap that reported a failure, a teardown whose upload hook raised. On
2026-10-08 that was twelve directories and 45 GB, and the VPS at 98%.

So this runs live only, on a clock and whenever free space falls to low or
critical (`disk_pressure`), over the directories themselves. A directory is
deleted only when deleting it loses nothing, and every clause is PROVEN; any
error or unknown keeps it with a `RetainedReason` that /health counts (#1983):

* fully readable: the walk that sizes it saw all of it;
* no session capture inside (design 1.3);
* no container of any name, in any state, binds it or anything below it;
* exactly one owner, whose Execution is terminal and has been for the settle
  period, read from the execution read model's terminal event, never mtimes;
* the owner's session captures all went to spool volumes;
* clean, unstashed, nothing unversioned outside proven caches, and every
  commit shown by ``git ls-remote`` on a repository the Execution names
  (`guard_stale_workspace_dir`).

Nothing is archived (that is slice 2), so nothing is "saved first": a dirty
directory stays and is reported. A directory that passes is CLAIMED (renamed
out of its workspace path, atomically) and then judged again in full, with
its identity checked, before it is deleted. Maintenance pauses every pass.
Any doubt about the inputs - docker unreadable, a read model rebuilding,
subscriptions catching up - skips the whole pass, because "I could not look"
must never read as "nothing is there".
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.orchestration import (
    ReclaimableDir,
    Retained,
    RetainedReason,
    StaleWorkspaceDir,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_adapters.workspace_backends.stale_dirs import (
        ContainerMounts,
        WorkspaceDirListing,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
        SessionSummary,
    )
    from syn_domain.contexts.orchestration import (
        HostWorkspaceGit,
        OwnerExecution,
        RemoteRefs,
    )
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
        WorkflowExecutionSummary,
    )
    from syn_domain.pagination import Page

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetainedDir:
    """One directory a pass kept, and why."""

    workspace_id: str
    reason: RetainedReason
    detail: str
    size_bytes: int


@dataclass(frozen=True)
class ReclaimPass:
    """What one pass did. ``skipped`` or ``paused`` names why it did not look at all."""

    reclaimed: tuple[str, ...] = ()
    reclaimed_bytes: int = 0
    retained: tuple[RetainedDir, ...] = ()
    #: Directories a dry run found reclaimable and left alone.
    would_reclaim: tuple[str, ...] = ()
    #: Directories proven lossless whose delete ran out of the pass's time; the
    #: next pass (or the first after a restart) finishes them.
    deleting: tuple[str, ...] = ()
    #: Whether the pass stopped at its time budget with directories unvisited.
    out_of_time: bool = False
    skipped: str | None = None
    paused: str | None = None

    @property
    def kept(self) -> tuple[str, ...]:
        return tuple(r.workspace_id for r in self.retained)


@dataclass
class WorkspaceDirReclaimer:
    """One reclaim pass over the workspace base directory, with its collaborators."""

    base_dir: str
    settle_seconds: float
    list_containers: Callable[[], Awaitable[list[ContainerMounts]]]
    workspace_owners: Callable[[str], Awaitable[set[str]]]
    execution_record: Callable[[str], Awaitable[OwnerExecution | None]]
    #: Why session capture may still be in the owner's workspace, or None.
    capture_unproven: Callable[[str], Awaitable[str | None]]
    scan_dirs: Callable[[str], list[WorkspaceDirListing]]
    git: HostWorkspaceGit
    remotes: RemoteRefs
    clock: Callable[[], float] = field(default=time.time)
    #: Wall seconds one pass may spend; deletes stop at it and resume next pass.
    pass_budget_seconds: float = 300.0
    monotonic: Callable[[], float] = field(default=time.monotonic)
    #: Rename a claimed, re-judged directory to its deleting name (blocking).
    mark_deleting: Callable[[str, tuple[int, int]], str] = field(
        default=lambda claimed, identity: _mark_deleting(claimed, identity)
    )
    #: Delete a deleting-named tree until a monotonic deadline; whether it is gone.
    delete_tree: Callable[[str, float], bool] = field(
        default=lambda path, deadline: _delete_tree(path, deadline)
    )
    #: Whether side effects may run now; read again just before each deletion.
    is_live: Callable[[], bool] = field(default=lambda: True)
    #: Why passes are paused now (maintenance), or None.
    paused: Callable[[], Awaitable[str | None]] = field(default=lambda: _not_paused())
    #: Rename a directory out of its workspace path; return where (blocking).
    claim: Callable[[str], str] = field(default=lambda host_dir: _claim(host_dir))
    #: Put a claimed directory back at its workspace path (blocking).
    release: Callable[[str], None] = field(default=lambda claimed: _release(claimed))
    #: Why the read models this pass trusts may be incomplete, or None when
    #: they are known whole. A rebuild clears them while `is_live` stays true.
    read_models_rebuilding: Callable[[], Awaitable[str | None]] = field(
        default=lambda: _known_whole()
    )
    dry_run: bool = False

    async def run_once(self) -> ReclaimPass:
        """Judge every directory; reclaim the ones that lose nothing. Never raises."""
        observed = await self._observe_pass()
        if isinstance(observed, ReclaimPass):
            return observed
        containers, listings = observed

        from syn_adapters.workspace_backends.stale_dirs import is_being_deleted

        deadline = self.monotonic() + self.pass_budget_seconds
        tally = _PassTally(dry_run=self.dry_run)
        # Unfinished deletes first: they are already proven, and finishing them
        # is what frees space soonest.
        for listing in sorted(listings, key=lambda x: not is_being_deleted(x.host_dir)):
            if self.monotonic() >= deadline:
                tally.out_of_time = True
                break
            # Maintenance set mid-pass stops it before the next directory, so
            # an operator holding maintenance knows no new delete will start.
            tally.paused = await self._paused_now()
            if tally.paused is not None:
                break
            tally.add(listing, await self._reclaim(listing, containers, deadline))
        return tally.result()

    async def _observe_pass(
        self,
    ) -> ReclaimPass | tuple[list[ContainerMounts], list[WorkspaceDirListing]]:
        """What the pass will look at, or why it will not look at all."""
        try:
            paused = await self.paused()
            if paused is not None:
                logger.info("Workspace reclaim pass paused: %s", paused)
                return ReclaimPass(paused=paused)
            rebuilding = await self.read_models_rebuilding()
            if rebuilding is not None:
                logger.info("Workspace reclaim pass skipped: %s", rebuilding)
                return ReclaimPass(skipped=rebuilding)
            containers = await self.list_containers()
            listings = await asyncio.to_thread(self.scan_dirs, self.base_dir)
        except Exception as exc:
            logger.warning("Skipping workspace reclaim pass: %s", exc, exc_info=True)
            return ReclaimPass(skipped=f"{type(exc).__name__}: {exc}")
        return containers, listings

    async def _paused_now(self) -> str | None:
        try:
            return await self.paused()
        except Exception as exc:
            return f"maintenance unreadable: {_described(exc)}"

    async def judge(
        self, listing: WorkspaceDirListing, containers: list[ContainerMounts]
    ) -> StaleWorkspaceDir | Retained:
        """Every clause that does not read the directory's repositories."""
        on_disk = _judge_on_disk(listing, containers)
        if on_disk is not None:
            return on_disk
        return await self._judge_owner(listing)

    async def _judge_owner(self, listing: WorkspaceDirListing) -> StaleWorkspaceDir | Retained:
        from syn_domain.contexts.orchestration import judge_owner

        try:
            owners = await self.workspace_owners(listing.workspace_id)
        except Exception as exc:
            return Retained(RetainedReason.UNOWNED, f"ownership unreadable: {_described(exc)}")
        record = None
        if len(owners) == 1:
            try:
                record = await self.execution_record(next(iter(owners)))
            except Exception as exc:
                return Retained(
                    RetainedReason.NOT_TERMINAL, f"execution unreadable: {_described(exc)}"
                )
        verdict = judge_owner(owners, record, now=self.clock(), settle_seconds=self.settle_seconds)
        if verdict is not None:
            return verdict
        if record is None:  # judge_owner returns None only for a record
            return Retained(RetainedReason.NOT_TERMINAL, "no execution record")
        try:
            capture = await self.capture_unproven(record.execution_id)
        except Exception as exc:
            capture = f"capture records unreadable: {_described(exc)}"
        if capture is not None:
            return Retained(RetainedReason.CAPTURE_UNKNOWN, capture)
        return StaleWorkspaceDir(
            host_dir=listing.host_dir,
            workspace_id=listing.workspace_id,
            execution_id=record.execution_id,
            size_bytes=listing.size_bytes,
            remote_urls=record.repositories,
        )

    async def _guarded(
        self, listing: WorkspaceDirListing, containers: list[ContainerMounts]
    ) -> ReclaimableDir | Retained:
        from syn_domain.contexts.orchestration import guard_stale_workspace_dir

        stale = await self.judge(listing, containers)
        if isinstance(stale, Retained):
            return stale
        return await guard_stale_workspace_dir(stale, self.git, self.remotes)

    async def _reclaim(
        self, listing: WorkspaceDirListing, containers: list[ContainerMounts], deadline: float
    ) -> ReclaimableDir | Retained | _Deferred:
        """Judge, claim, judge again, mark, then delete within the pass's time.

        A dead pass's claim is put back if kept; a dead pass's delete (a
        ``.deleting-`` directory) is finished, never judged again or put back.
        """
        from syn_adapters.workspace_backends.stale_dirs import is_being_deleted

        if is_being_deleted(listing.host_dir):
            return await self._resume_delete(listing, containers, deadline)
        verdict = await self._guarded(listing, containers)
        if isinstance(verdict, Retained) or self.dry_run:
            await self._put_back(listing.host_dir)
            _log_outcome(listing, verdict, dry_run=self.dry_run)
            return verdict
        try:
            claimed = await asyncio.to_thread(self.claim, listing.host_dir)
        except OSError as exc:
            kept = Retained(RetainedReason.IDENTITY_CHANGED, f"could not claim it ({exc})")
            _log_outcome(listing, kept)
            return kept
        again = await self._judge_claimed(listing, claimed)
        if isinstance(again, Retained):
            await self._put_back(claimed)
            _log_outcome(listing, again)
            return again
        try:
            marked = await asyncio.to_thread(self.mark_deleting, claimed, listing.identity)
        except OSError as exc:
            await self._put_back(claimed)
            kept = Retained(RetainedReason.IDENTITY_CHANGED, f"could not mark it ({exc})")
            _log_outcome(listing, kept)
            return kept
        # Judged at the claimed path; logged under the path it was found at.
        return await self._finish_delete(
            listing, replace(again, host_dir=listing.host_dir), marked, deadline
        )

    async def _resume_delete(
        self, listing: WorkspaceDirListing, containers: list[ContainerMounts], deadline: float
    ) -> ReclaimableDir | Retained | _Deferred:
        """Finish a delete a pass or a restart left; it was proven before it began."""
        binding = [c.container_id[:12] for c in containers if c.mounts(listing.workspace_id)]
        if binding:
            kept = Retained(RetainedReason.MOUNTED, f"bound by container(s) {binding}")
            _log_outcome(listing, kept)
            return kept
        if self.dry_run:
            return _Deferred()
        resumed = ReclaimableDir(
            host_dir=listing.host_dir,
            workspace_id=listing.workspace_id,
            size_bytes=listing.size_bytes,
        )
        return await self._finish_delete(listing, resumed, listing.host_dir, deadline)

    async def _finish_delete(
        self, listing: WorkspaceDirListing, reclaimable: ReclaimableDir, at: str, deadline: float
    ) -> ReclaimableDir | Retained | _Deferred:
        """Delete ``at`` off the event loop until the pass's deadline.

        Only ever reached with a `ReclaimableDir` (or a ``.deleting-`` name,
        which only a `ReclaimableDir` produces), so nothing unguarded is deleted.

        Scratch only (owner decision, #1983): the one thing this ever deletes
        is a direct child of the workspace base directory. Run history - the
        event store, Postgres, MinIO artifacts, transcripts, telemetry - is
        kept for every run, failed ones included, and is never reached here.
        """
        if Path(at).parent != Path(self.base_dir):
            refused = Retained(
                RetainedReason.DELETE_FAILED, f"refusing {at}: not directly under the base dir"
            )
            _log_outcome(listing, refused)
            return refused
        try:
            done = await asyncio.to_thread(self.delete_tree, at, deadline)
        except (OSError, ValueError) as exc:
            failed = Retained(RetainedReason.DELETE_FAILED, f"could not delete {at}: {exc}")
            _log_outcome(listing, failed)
            return failed
        if not done:
            logger.info(
                "WorkspaceReclaimOutcome workspace_id=%s bytes=%d outcome=deleting "
                "reason= detail=out of time this pass; resumes next pass",
                listing.workspace_id,
                listing.size_bytes,
            )
            return _Deferred()
        logger.info(
            "WorkspaceReclaimed workspace_id=%s host_dir=%s size_bytes=%d",
            reclaimable.workspace_id,
            reclaimable.host_dir,
            reclaimable.size_bytes,
        )
        _log_outcome(listing, reclaimable)
        return reclaimable

    async def _judge_claimed(
        self, before: WorkspaceDirListing, claimed: str
    ) -> ReclaimableDir | Retained:
        """Read everything again under the claim; any doubt is a reason to keep it."""
        catching_up = Retained(
            RetainedReason.NOT_TERMINAL, "subscriptions began catching up under the claim"
        )
        if not self.is_live():
            return catching_up
        try:
            rebuilding = await self.read_models_rebuilding()
            containers = await self.list_containers()
            listings = await asyncio.to_thread(self.scan_dirs, self.base_dir)
        except Exception as exc:
            return Retained(RetainedReason.UNREADABLE, f"could not look again: {_described(exc)}")
        if rebuilding is not None:
            return Retained(RetainedReason.NOT_TERMINAL, f"read models rebuilding: {rebuilding}")
        listing = next((x for x in listings if x.host_dir == claimed), None)
        if listing is None or listing.identity != before.identity:
            return Retained(RetainedReason.IDENTITY_CHANGED, "it was replaced under the claim")
        verdict = await self._guarded(listing, containers)
        if isinstance(verdict, Retained):
            return verdict
        return verdict if self.is_live() else catching_up

    async def _put_back(self, path: str) -> None:
        """A claimed directory that is kept goes back to its workspace path."""
        try:
            await asyncio.to_thread(self.release, path)
        except OSError:
            logger.exception(
                "Claimed workspace directory %s could not be put back; it stays where it is", path
            )


@dataclass(frozen=True)
class _Deferred:
    """A proven directory whose delete continues next pass."""


def _judge_on_disk(
    listing: WorkspaceDirListing, containers: list[ContainerMounts]
) -> Retained | None:
    """The clauses the listing and docker answer: readable, no capture, unbound."""
    if listing.unreadable is not None:
        return Retained(RetainedReason.UNREADABLE, listing.unreadable)
    if listing.session_store:
        return Retained(RetainedReason.CAPTURE_UNKNOWN, "a session store is inside the directory")
    binding = [c.container_id[:12] for c in containers if c.mounts(listing.workspace_id)]
    if binding:
        return Retained(RetainedReason.MOUNTED, f"bound by container(s) {binding}")
    return None


@dataclass
class _PassTally:
    """What a pass did so far, directory by directory."""

    dry_run: bool
    reclaimed: list[str] = field(default_factory=list)
    reclaimed_bytes: int = 0
    retained: list[RetainedDir] = field(default_factory=list)
    would: list[str] = field(default_factory=list)
    deleting: list[str] = field(default_factory=list)
    paused: str | None = None
    out_of_time: bool = False

    def add(self, listing: WorkspaceDirListing, outcome: object) -> None:
        if isinstance(outcome, Retained):
            self.retained.append(
                RetainedDir(
                    listing.workspace_id, outcome.reason, outcome.detail, listing.size_bytes
                )
            )
        elif isinstance(outcome, _Deferred):
            self.deleting.append(listing.workspace_id)
        elif self.dry_run:
            self.would.append(listing.workspace_id)
        else:
            self.reclaimed.append(listing.workspace_id)
            self.reclaimed_bytes += listing.size_bytes

    def result(self) -> ReclaimPass:
        result = ReclaimPass(
            reclaimed=tuple(self.reclaimed),
            reclaimed_bytes=self.reclaimed_bytes,
            retained=tuple(self.retained),
            would_reclaim=tuple(self.would),
            deleting=tuple(self.deleting),
            out_of_time=self.out_of_time or bool(self.deleting),
            paused=self.paused,
        )
        logger.info(
            "Workspace reclaim pass: reclaimed %d (%d bytes), retained %d, "
            "deleting %d, dry-run %d, out of time %s",
            len(self.reclaimed),
            self.reclaimed_bytes,
            len(self.retained),
            len(self.deleting),
            len(self.would),
            result.out_of_time,
        )
        return result


def _log_outcome(
    listing: WorkspaceDirListing, outcome: ReclaimableDir | Retained, *, dry_run: bool = False
) -> None:
    """One structured line per directory (Lane 2 only)."""
    if isinstance(outcome, Retained):
        result, reason, detail = "retained", outcome.reason.value, outcome.detail
    else:
        result, reason, detail = ("dry_run" if dry_run else "reclaimed"), "", ""
    logger.info(
        "WorkspaceReclaimOutcome workspace_id=%s bytes=%d outcome=%s reason=%s detail=%s",
        listing.workspace_id,
        listing.size_bytes,
        result,
        reason,
        detail,
    )


def _described(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _claim(host_dir: str) -> str:
    from syn_adapters.workspace_backends.stale_dirs import claim_workspace_dir

    return claim_workspace_dir(host_dir)


def _mark_deleting(claimed: str, identity: tuple[int, int]) -> str:
    from syn_adapters.workspace_backends.stale_dirs import mark_for_deletion

    return mark_for_deletion(claimed, identity)


def _delete_tree(path: str, deadline: float) -> bool:
    from syn_adapters.workspace_backends.stale_dirs import delete_tree_until

    return delete_tree_until(path, deadline, time.monotonic)


def _release(claimed: str) -> None:
    from syn_adapters.workspace_backends.stale_dirs import release_workspace_dir

    release_workspace_dir(claimed)


async def _known_whole() -> str | None:
    return None


async def _not_paused() -> str | None:
    return None


async def _reclaim_inputs_rebuilding() -> str | None:
    """Whether the execution list or the ownership links are being rebuilt."""
    from syn_api.services.read_model_status import read_models_rebuilding
    from syn_domain.contexts.orchestration.slices.list_executions.projection import (
        WorkflowExecutionListProjection,
    )
    from syn_domain.contexts.orchestration.slices.workspace_ownership.projection import (
        WorkspaceOwnershipProjection,
    )

    return await read_models_rebuilding(
        {
            WorkflowExecutionListProjection.PROJECTION_NAME,
            WorkspaceOwnershipProjection.PROJECTION_NAME,
        }
    )


async def _maintenance_paused() -> str | None:
    from syn_api._wiring_admission import get_maintenance_port

    return "maintenance" if (await get_maintenance_port().current()).active else None


def _epoch(value: datetime | str | None) -> float | None:
    if value is None:
        return None
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


class ExecutionRows(Protocol):
    async def get_by_id(self, execution_id: str) -> WorkflowExecutionSummary | None: ...


class SpoolIndex(Protocol):
    async def session_ids(self, execution_id: str) -> set[str]: ...


class SessionPages(Protocol):
    async def page(
        self, *, execution_id: str | None = None, limit: int | None = None
    ) -> Page[SessionSummary]: ...


async def execution_record_from(rows: ExecutionRows, execution_id: str) -> OwnerExecution | None:
    """The owner as the execution read model has it, keyed by its id."""
    from syn_domain.contexts.orchestration import TERMINAL_EXECUTION_STATUSES, OwnerExecution

    row = await rows.get_by_id(execution_id)
    if row is None:
        return None
    terminal = row.status in TERMINAL_EXECUTION_STATUSES
    return OwnerExecution(
        execution_id=row.workflow_execution_id,
        status=row.status,
        terminal_at=_epoch(row.completed_at) if terminal else None,
        repositories=row.repos,
    )


async def capture_unproven_from(
    spools: SpoolIndex, sessions: SessionPages, execution_id: str
) -> str | None:
    """Why the owner's capture may be in its workspace (design 1.3), or None.

    Every top-level session of the execution must have a spool record: AW
    lets only ``/spool`` outlive a container, and syn137 mounts it as a named
    volume. No session recorded at all is not proof either.
    """
    spooled = await spools.session_ids(execution_id)
    page = await sessions.page(execution_id=execution_id, limit=None)
    top_level = {row.id for row in page.rows if row.parent_session_id is None}
    if not top_level:
        return "no session of the execution is recorded"
    missing = sorted(top_level - spooled)
    if missing:
        return f"{len(missing)} session(s) have no spool capture record, e.g. {missing[0]}"
    return None


async def _execution_record(execution_id: str) -> OwnerExecution | None:
    from syn_api._wiring import get_projection_mgr

    return await execution_record_from(get_projection_mgr().workflow_execution_list, execution_id)


async def _capture_unproven(execution_id: str) -> str | None:
    from syn_api._wiring import get_projection_mgr
    from syn_api._wiring_inventory import get_inventory_runtime

    return await capture_unproven_from(
        get_inventory_runtime().spools, get_projection_mgr().session_list, execution_id
    )


def default_reclaimer(is_live: Callable[[], bool]) -> WorkspaceDirReclaimer:
    """The production wiring: docker, the read models, host git, the real remote."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.workspace_backends.orphaned import workspace_base_dir
    from syn_adapters.workspace_backends.remote_refs import GitLsRemote, github_app_credential
    from syn_adapters.workspace_backends.stale_dirs import (
        SubprocessHostWorkspaceGit,
        list_containers,
        scan_workspace_dirs,
    )
    from syn_domain.contexts.orchestration.slices.workspace_ownership.projection import (
        WorkspaceOwnershipProjection,
    )
    from syn_shared.settings import get_settings

    disk = get_settings().disk
    return WorkspaceDirReclaimer(
        base_dir=workspace_base_dir(),
        settle_seconds=disk.reclaim_settle_minutes * 60,
        list_containers=list_containers,
        workspace_owners=WorkspaceOwnershipProjection(get_projection_store()).owners,
        execution_record=_execution_record,
        capture_unproven=_capture_unproven,
        scan_dirs=scan_workspace_dirs,
        git=SubprocessHostWorkspaceGit(),
        remotes=GitLsRemote(github_app_credential),
        pass_budget_seconds=disk.reclaim_pass_budget_minutes * 60,
        is_live=is_live,
        paused=_maintenance_paused,
        read_models_rebuilding=_reclaim_inputs_rebuilding,
        dry_run=disk.reclaim_dry_run,
    )


async def reclaim_on_a_clock(
    reclaimer: WorkspaceDirReclaimer,
    *,
    is_live: Callable[[], bool],
    interval_seconds: float,
    wake: asyncio.Event | None = None,
) -> None:
    """Run a pass every ``interval_seconds``, or when ``wake`` is set; only while live.

    Live only: during catch-up the execution list is still being rebuilt, and
    an execution it has not replayed yet would read as not terminal at best.
    """
    from syn_api.services.workspace_reclaim_status import reclaim_status

    while True:
        if wake is None:
            await asyncio.sleep(interval_seconds)
        else:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), timeout=interval_seconds)
            wake.clear()
        if not is_live():
            logger.info("Workspace reclaim pass skipped: subscriptions are catching up")
            reclaim_status().record(
                ReclaimPass(skipped="subscriptions are catching up"), at=time.time()
            )
            continue
        reclaim_status().record(await reclaimer.run_once(), at=time.time())


_reclaim_task: asyncio.Task[None] | None = None


class _Subscriptions(Protocol):
    @property
    def is_live(self) -> bool: ...


def start_workspace_reclaim(subscriptions: Callable[[], _Subscriptions | None]) -> None:
    """Start the clock, once. Called after subscriptions are live.

    ``subscriptions`` returns the coordinator the API holds at each call, not
    the one it held at start: the clock starts once, and a recovery re-run of
    the init replaces the coordinator under it. None is not live. Low disk
    (`disk_pressure`) wakes it between ticks.
    """
    global _reclaim_task
    if _reclaim_task is not None and not _reclaim_task.done():
        return
    from syn_api.services.disk_pressure import pressure_event
    from syn_shared.settings import get_settings

    def is_live() -> bool:
        current = subscriptions()
        return current is not None and current.is_live

    _reclaim_task = asyncio.create_task(
        reclaim_on_a_clock(
            default_reclaimer(is_live),
            is_live=is_live,
            interval_seconds=get_settings().disk.reclaim_interval_minutes * 60,
            wake=pressure_event(),
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
