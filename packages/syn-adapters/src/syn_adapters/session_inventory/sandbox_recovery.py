"""Reopen a paused sandbox's capture spool from its durable row (#1916).

Design: docs/research/2026-10-08-remote-executor-e2b.md, decision 7.

The spool lives on the sandbox's own disk at ``/spool``, retained by pausing the
sandbox rather than by a volume. Recovery resumes it, stops and confirms every
agent writer gone, then reads with the same execute-based readers Docker uses.
Leaving the context pauses the sandbox again while the lease is still ours: only
release, after ``mark_drained``, kills it.

Reaching a sandbox is not permission to stop it, or to pause it. That comes from
durable state only: the lease is settled (no executor will resume the session)
and still ours, checked before attach, again after it, since attach can be slow,
and again before the closing pause. Once the lease is lost the sandbox belongs
to its new owner, which resumes and pauses it itself.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol

from agentic_isolation.child_journal import WorkspaceChildJournalReader
from agentic_isolation.session_spool import WorkspaceSpoolReader, capture_retained_partition

from syn_domain.contexts.agent_sessions import CaptureSpoolLeaseLost

from .recovery_worker import RecoveryReaders
from .workspace_location import workspace_capture_location

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from agentic_isolation.harnesses import ExecFn

    from syn_domain.contexts.agent_sessions import CaptureSpool, CaptureSpoolLease


logger = logging.getLogger(__name__)


class SpoolNotSettled(Exception):
    """Recovery would stop the writer of a session an executor may still resume."""


class RecoverySandbox(Protocol):
    """One attached sandbox, resumed for the duration of a recovery."""

    @property
    def execute(self) -> ExecFn: ...

    async def stop_writers(self) -> bool:
        """Stop every agent process; True only once the provider confirms none remain.

        Any failure or ambiguity is False. FIXME(#1916): no production
        adapter yet. At the pinned agentic-workspace (fb696fd8) E2B operations
        live only in the starting process ("There is no reattach",
        ``e2b_operations.py``), so a fresh worker's ``cancel`` of the dead
        executor's operation is ``unknown_operation``, and the provider has no
        public pause. AW#103 added ``SupportsOperationReattach`` and
        ``SupportsWorkspaceSuspend`` (release 896449c5, pinned by #2149). The
        adapter then also needs the executor to persist the writer's
        ``OperationRef`` and reattach token, a credential, on this row.
        """
        ...


class RecoverySandboxes(Protocol):
    """The recovery kit for one backend and account (decision 8)."""

    async def resume(self, sandbox_id: str, *, executor_id: str) -> RecoverySandbox:
        """Resume ``sandbox_id`` after an ownership check against ``executor_id``.

        Raising means the sandbox is paused, as it was: a resume that may have
        applied (its response lost) is paused again before raising. The caller
        cannot pause after a failed resume, because a failed ownership check
        must never touch the sandbox; only the adapter knows which it was.
        """
        ...

    async def pause(self, sandbox_id: str) -> None:
        """Pause ``sandbox_id`` again; its disk, and so the spool, is kept."""
        ...

    async def writers_stopped(self, sandbox_id: str, *, executor_id: str) -> bool:
        """True only when the provider confirms no agent process remains.

        A status query: it never resumes, stops or pauses anything. Unknown is
        False. FIXME(#1916): the same reattach gap as ``stop_writers``:
        ``SupportsOperations.status`` answers only in the starting process.
        """
        ...

    async def kill(self, sandbox_id: str) -> bool:
        """True when killed or already gone; False keeps it paused."""
        ...


class SandboxSpoolRecovery:
    """``SpoolRecoveryPort`` and ``SpoolVolumePort`` for a sandbox backend.

    Satisfies both because release has to reach the same sandbox recovery
    opened: removing a sandbox spool is killing the sandbox.
    """

    def __init__(self, sandboxes: RecoverySandboxes) -> None:
        self._sandboxes = sandboxes

    @asynccontextmanager
    async def open(
        self, lease: CaptureSpoolLease, *, fence: Callable[[], Awaitable[None]]
    ) -> AsyncIterator[RecoveryReaders]:
        spool = lease.spool
        sandbox_id, executor_id = _route(spool)
        if not lease.settled:
            raise SpoolNotSettled(
                f"Spool {spool.session_id} in sandbox {sandbox_id} is not settled; "
                "its executor may still resume it, so recovery will not stop its agent"
            )
        location = workspace_capture_location(spool.run, spool.session_id)
        lost = False

        async def fenced() -> None:
            nonlocal lost
            try:
                await fence()
            except CaptureSpoolLeaseLost:
                lost = True
                raise

        await fenced()
        sandbox = await self._sandboxes.resume(sandbox_id, executor_id=executor_id)
        try:
            await fenced()
            # Resuming resumes the agent too. A run in fencing or a disconnected
            # stream says nothing about whether it still writes: only the
            # provider's confirmation makes this traversal exclusive.
            try:
                exclusive = await sandbox.stop_writers()
            except Exception:
                exclusive = False
            await capture_retained_partition(sandbox.execute, "/spool", location.partition)
            yield RecoveryReaders(
                transcripts=WorkspaceSpoolReader(sandbox.execute, location.envelope_dir),
                children=WorkspaceChildJournalReader(
                    sandbox.execute,
                    f"/spool/.agentic-session-store/{location.partition}/children.sqlite",
                ),
                exclusive=exclusive,
            )
        except CaptureSpoolLeaseLost:
            lost = True
            raise
        finally:
            # A stale worker leaves the sandbox to whoever holds the lease now:
            # pausing it would cut that worker's reads off mid-traversal.
            if not lost:
                try:
                    await fenced()
                except CaptureSpoolLeaseLost:
                    pass
                except Exception:
                    # Ownership unknown: this worker was the last confirmed owner,
                    # and a running sandbox is the costlier failure.
                    logger.exception("Spool fence failed before pausing sandbox %s", sandbox_id)
            if not lost:
                await self._sandboxes.pause(sandbox_id)

    async def remove(self, spool: CaptureSpool) -> bool:
        # Evicting bytes is not permission to end a run: a quota or age limit
        # reaching a sandbox whose agent still runs keeps it until that stops.
        # FIXME(#1916): a paused writer never stops on its own, and an expired
        # row is no longer claimable by recovery, so a settled sandbox expired
        # with a live writer stays paused until an operator acts. The fix needs
        # writer confirmation (see ``stop_writers``) to stop it under a lease
        # before the kill; until then this fails closed (paused, never killed).
        sandbox_id, executor_id = _route(spool)
        if not await self._sandboxes.writers_stopped(sandbox_id, executor_id=executor_id):
            return False
        return await self._sandboxes.kill(sandbox_id)


def _route(spool: CaptureSpool) -> tuple[str, str]:
    if spool.sandbox_id is None or spool.executor_id is None:
        raise ValueError("Spool row does not name a sandbox")
    return spool.sandbox_id, spool.executor_id
