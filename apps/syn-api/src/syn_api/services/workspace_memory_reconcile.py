"""Run the workspace memory reconciler on a clock (okrs-51p.30, #2148).

Started with the execution host, so in every process that creates
workspaces, Run Queue on or off; a tick with nothing leaked lists nothing.
Docker only: the listing reads this host's daemon, and an E2B sandbox is
neither listed there nor charged to this host's memory.
"""

from __future__ import annotations

import asyncio
import contextlib

from syn_adapters.workspace_backends.service.memory_reconciler import (
    MEMORY_RECONCILE_INTERVAL_SECONDS,
    DockerWorkspacePresence,
    WorkspaceMemoryReconciler,
)

_reconcile_task: asyncio.Task[None] | None = None


def start() -> None:
    """Start the reconciler, once; nothing when workspaces are not local Docker."""
    global _reconcile_task
    if _reconcile_task is not None and not _reconcile_task.done():
        return
    from syn_api._wiring_workspace_memory import get_workspace_memory_ledger, ledger_applies

    if not ledger_applies():
        return
    reconciler = WorkspaceMemoryReconciler(get_workspace_memory_ledger(), DockerWorkspacePresence())
    _reconcile_task = asyncio.create_task(
        reconciler.run_on_a_clock(MEMORY_RECONCILE_INTERVAL_SECONDS),
        name="workspace-memory-reconciler",
    )


async def stop() -> None:
    """Stop the reconciler; a no-op if never started."""
    global _reconcile_task
    task, _reconcile_task = _reconcile_task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
