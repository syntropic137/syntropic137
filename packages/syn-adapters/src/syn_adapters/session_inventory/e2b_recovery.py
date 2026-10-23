"""Reopen a paused sandbox's capture spool from its durable row (#1916, decision 7).

The spool lives on the sandbox's own disk at ``/spool``, retained by pausing the
sandbox rather than by a volume. Recovery resumes it, stops and confirms every
agent writer gone, then reads with the same execute-based readers Docker uses.
Leaving the context pauses the sandbox again: only release, after
``mark_drained``, kills it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol

from agentic_isolation.child_journal import WorkspaceChildJournalReader
from agentic_isolation.session_spool import WorkspaceSpoolReader, capture_retained_partition

from .recovery_worker import RecoveryReaders
from .workspace_location import workspace_capture_location

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from contextlib import AbstractAsyncContextManager

    from agentic_isolation.harnesses import ExecFn

    from syn_domain.contexts.agent_sessions import CaptureSpool


class RecoverySandbox(Protocol):
    """One attached sandbox, resumed for the duration of a recovery."""

    @property
    def execute(self) -> ExecFn: ...

    async def stop_writers(self) -> bool:
        """Stop every agent process; True only once the provider confirms none remain.

        Any failure or ambiguity is False. FIXME(#1916): satisfied by
        agentic-workspace ``SupportsOperations.cancel`` (pinned on #2076); the
        pin this branch builds on has no E2B implementation, so no production
        adapter exists yet.
        """
        ...


class RecoverySandboxes(Protocol):
    """The recovery kit for one backend and account (decision 8)."""

    def attach(
        self, sandbox_id: str, *, executor_id: str
    ) -> AbstractAsyncContextManager[RecoverySandbox]:
        """Resume ``sandbox_id`` after an ownership check against ``executor_id``.

        Leaving the context pauses it again, whatever happened inside.
        """
        ...

    async def kill(self, sandbox_id: str) -> bool:
        """True when killed or already gone; False keeps it paused."""
        ...


class RemoteSpoolRecovery(Protocol):
    """What the inventory runtime needs from a remote backend: open and remove."""

    def open(self, spool: CaptureSpool) -> AbstractAsyncContextManager[RecoveryReaders]: ...

    async def remove(self, spool: CaptureSpool) -> bool: ...


class SandboxSpoolRecovery:
    def __init__(self, sandboxes: RecoverySandboxes) -> None:
        self._sandboxes = sandboxes

    @asynccontextmanager
    async def open(self, spool: CaptureSpool) -> AsyncIterator[RecoveryReaders]:
        sandbox_id, executor_id = _route(spool)
        location = workspace_capture_location(spool.run, spool.session_id)
        async with self._sandboxes.attach(sandbox_id, executor_id=executor_id) as sandbox:
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

    async def remove(self, spool: CaptureSpool) -> bool:
        sandbox_id, _ = _route(spool)
        return await self._sandboxes.kill(sandbox_id)


def _route(spool: CaptureSpool) -> tuple[str, str]:
    if spool.sandbox_id is None or spool.executor_id is None:
        raise ValueError("Spool row does not name a sandbox")
    return spool.sandbox_id, spool.executor_id
