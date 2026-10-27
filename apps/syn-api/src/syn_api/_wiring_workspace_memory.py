"""The process-wide workspace memory ledger (okrs-51p.30).

One per process, like the execution budget: a limit is only a limit if every
workspace reserves from the same one, and ``get_execution_processor()`` builds
a new processor, and so a new ``WorkspaceService``, per launch.

Local Docker only (``ledger_applies``): the ledger accounts for THIS host's
memory, and an E2B sandbox spends none of it.
"""

from __future__ import annotations

from syn_adapters.workspace_backends.service.memory_ledger import (
    WorkspaceMemoryLedger,
    ledger_capacity_mb,
)

_ledger_singleton: WorkspaceMemoryLedger | None = None


def ledger_applies() -> bool:
    """Whether workspaces here are local Docker containers, the only kind the ledger counts."""
    from syn_adapters.workspace_backends.service import WorkspaceBackend
    from syn_shared.settings import get_settings

    return WorkspaceBackend.selected(get_settings().e2b) is WorkspaceBackend.DOCKER


def get_workspace_memory_ledger() -> WorkspaceMemoryLedger:
    """The ledger every workspace in this process reserves its memory from."""
    global _ledger_singleton
    if _ledger_singleton is None:
        from syn_shared.settings import get_settings

        settings = get_settings()
        _ledger_singleton = WorkspaceMemoryLedger(
            ledger_capacity_mb(
                settings.execution.max_concurrent, settings.workspace.memory_limit_mb
            )
        )
    return _ledger_singleton
