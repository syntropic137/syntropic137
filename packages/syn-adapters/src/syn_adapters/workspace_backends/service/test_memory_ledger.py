"""The workspace memory ledger: a big workspace counts as more than one run (okrs-51p.30)."""

from __future__ import annotations

import asyncio

import pytest

from syn_adapters.workspace_backends.service.memory_ledger import (
    WorkspaceMemoryLedger,
    ledger_capacity_mb,
)

pytestmark = pytest.mark.unit


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_default_workspaces_up_to_the_run_budget_never_wait() -> None:
    """With nothing requested, the ledger admits exactly what the budget does."""
    ledger = WorkspaceMemoryLedger(ledger_capacity_mb(4, 4096))

    held = [await ledger.reserve(4096, workspace_id=f"ws-{i}") for i in range(4)]

    assert ledger.reserved_mb == 16384
    assert ledger.waiting == 0
    for reservation in held:
        reservation.release()
    assert ledger.reserved_mb == 0


async def test_a_large_workspace_waits_until_its_shares_are_free() -> None:
    ledger = WorkspaceMemoryLedger(16384)
    small = await ledger.reserve(4096, workspace_id="small")

    big = asyncio.create_task(ledger.reserve(16384, workspace_id="big"))
    await _settle()
    assert not big.done()
    assert ledger.waiting == 1

    small.release()
    reservation = await asyncio.wait_for(big, timeout=1)
    assert ledger.reserved_mb == 16384
    reservation.release()


async def test_a_small_workspace_never_barges_past_a_waiting_large_one() -> None:
    """Without FIFO a stream of 4 GB phases would starve a 16 GB build forever."""
    ledger = WorkspaceMemoryLedger(16384)
    first = await ledger.reserve(4096, workspace_id="first")
    big = asyncio.create_task(ledger.reserve(16384, workspace_id="big"))
    await _settle()

    late_small = asyncio.create_task(ledger.reserve(4096, workspace_id="late"))
    await _settle()
    assert not late_small.done(), "fits by itself, but the big one is ahead of it"

    first.release()
    big_reservation = await asyncio.wait_for(big, timeout=1)
    assert not late_small.done()
    big_reservation.release()
    (await asyncio.wait_for(late_small, timeout=1)).release()


async def test_a_request_larger_than_the_whole_ledger_runs_alone_rather_than_never() -> None:
    ledger = WorkspaceMemoryLedger(4096)

    reservation = await asyncio.wait_for(ledger.reserve(16384, workspace_id="huge"), timeout=1)

    assert ledger.reserved_mb == 16384
    reservation.release()


async def test_a_waiter_cancelled_in_the_queue_gives_its_place_back() -> None:
    ledger = WorkspaceMemoryLedger(8192)
    held = await ledger.reserve(8192, workspace_id="held")
    cancelled = asyncio.create_task(ledger.reserve(8192, workspace_id="cancelled"))
    behind = asyncio.create_task(ledger.reserve(4096, workspace_id="behind"))
    await _settle()

    cancelled.cancel()
    await _settle()
    held.release()

    (await asyncio.wait_for(behind, timeout=1)).release()
    assert ledger.reserved_mb == 0
    assert ledger.waiting == 0


async def test_release_is_idempotent() -> None:
    ledger = WorkspaceMemoryLedger(8192)
    reservation = await ledger.reserve(4096, workspace_id="ws")

    reservation.release()
    reservation.release()

    assert ledger.reserved_mb == 0


def test_a_ledger_without_capacity_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1 MB"):
        WorkspaceMemoryLedger(0)
