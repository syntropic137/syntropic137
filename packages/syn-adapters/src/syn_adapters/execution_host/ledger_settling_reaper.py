"""The host's reaper, settling leaked workspace memory once a reap shows it gone (okrs-51p.30).

A workspace whose teardown failed keeps its memory charged in the
``WorkspaceMemoryLedger`` (see ``memory_ledger``). This is the one place that
charge is lifted while the process lives: the reap the host ALREADY performs
before closing a run, and the reconciler performs on a fenced run, proves by
listing that nothing labelled with the host and execution is left. Only a
reap of THIS host's runs settles, because the ledger is this process's.

No new cleanup path: this only listens to the existing one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.execution_host.ports import RunReaper
    from syn_adapters.workspace_backends.service.memory_ledger import WorkspaceMemoryLedger
    from syn_domain.contexts.orchestration.ports import IsolationLevel, ProviderId, ReapScope


class LedgerSettlingReaper:
    """A ``RunReaper`` that frees a run's leaked workspace memory when its reap shows it gone."""

    def __init__(self, reaper: RunReaper, ledger: WorkspaceMemoryLedger, host_id: str) -> None:
        self._reaper = reaper
        self._ledger = ledger
        self._host_id = host_id

    def scope(self) -> ReapScope:
        return self._reaper.scope()

    def provider(self) -> ProviderId:
        return self._reaper.provider()

    def isolation(self) -> IsolationLevel:
        return self._reaper.isolation()

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        gone = await self._reaper.reap(executor_id, execution_id)
        if gone and executor_id == self._host_id:
            self._ledger.settle_leaked(execution_id)
        return gone
