"""The host's existing reap is what frees a leaked workspace's memory (okrs-51p.30)."""

from __future__ import annotations

import pytest

from syn_adapters.execution_host.ledger_settling_reaper import LedgerSettlingReaper
from syn_adapters.workspace_backends.service.memory_ledger import WorkspaceMemoryLedger

pytestmark = pytest.mark.unit


class _Reaper:
    def __init__(self, gone: bool) -> None:
        self.gone = gone
        self.calls: list[tuple[str, str]] = []

    def scope(self) -> object:
        return "scope"

    def provider(self) -> object:
        return "docker"

    def isolation(self) -> object:
        return "container"

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        self.calls.append((executor_id, execution_id))
        return self.gone


async def _leaked_ledger() -> WorkspaceMemoryLedger:
    ledger = WorkspaceMemoryLedger(8192)
    (await ledger.reserve(4096, workspace_id="ws")).leak("exec-1", workspace_id="ws", reason="x")
    return ledger


async def test_a_reap_that_shows_this_hosts_run_gone_frees_its_leaked_memory() -> None:
    ledger = await _leaked_ledger()
    reaper = LedgerSettlingReaper(_Reaper(gone=True), ledger, "host-a")  # type: ignore[arg-type]

    assert await reaper.reap("host-a", "exec-1") is True
    assert ledger.reserved_mb == 0


async def test_a_reap_that_cannot_show_it_gone_keeps_it_charged() -> None:
    ledger = await _leaked_ledger()
    reaper = LedgerSettlingReaper(_Reaper(gone=False), ledger, "host-a")  # type: ignore[arg-type]

    assert await reaper.reap("host-a", "exec-1") is False
    assert ledger.reserved_mb == 4096


async def test_reaping_another_hosts_run_settles_nothing_here() -> None:
    ledger = await _leaked_ledger()
    reaper = LedgerSettlingReaper(_Reaper(gone=True), ledger, "host-a")  # type: ignore[arg-type]

    await reaper.reap("host-b", "exec-1")
    assert ledger.reserved_mb == 4096


def test_it_delegates_what_the_host_reads_off_the_backend() -> None:
    inner = _Reaper(gone=True)
    reaper = LedgerSettlingReaper(inner, WorkspaceMemoryLedger(1), "h")  # type: ignore[arg-type]
    assert (reaper.scope(), reaper.provider(), reaper.isolation()) == (
        "scope",
        "docker",
        "container",
    )
