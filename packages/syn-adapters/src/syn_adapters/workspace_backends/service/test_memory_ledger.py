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


async def test_an_oversize_request_at_the_head_holds_back_later_smalls_then_runs_alone() -> None:
    """Bigger than the whole ledger, queued behind live smalls: no barging, then alone."""
    ledger = WorkspaceMemoryLedger(8192)
    holders = [await ledger.reserve(4096, workspace_id=f"small-{i}") for i in range(2)]
    huge = asyncio.create_task(ledger.reserve(16384, workspace_id="huge"))
    await _settle()
    late = [asyncio.create_task(ledger.reserve(4096, workspace_id=f"late-{i}")) for i in range(2)]
    await _settle()
    assert not huge.done()
    assert not any(t.done() for t in late)

    holders[0].release()
    await _settle()
    assert not huge.done(), "one small still holds memory: the oversize waits to run alone"
    assert not any(t.done() for t in late), "a freed share must not go past the head"

    holders[1].release()
    huge_reservation = await asyncio.wait_for(huge, timeout=1)
    await _settle()
    assert ledger.reserved_mb == 16384
    assert not any(t.done() for t in late), "nothing runs beside the oversize one"

    huge_reservation.release()
    for reservation in [await asyncio.wait_for(t, timeout=1) for t in late]:
        reservation.release()
    assert ledger.reserved_mb == 0


_NONE: frozenset[str] = frozenset()


async def test_a_leaked_reservation_stays_charged_until_shown_absent() -> None:
    ledger = WorkspaceMemoryLedger(8192)
    reservation = await ledger.reserve(4096, workspace_id="ws")

    reservation.leak("exec-1", reason="teardown failed")
    reservation.release()  # final: a leak is not undone by a later release

    assert ledger.reserved_mb == 4096
    assert ledger.settle_absent(frozenset({"ws"}), _NONE) == 0, "still listed"
    assert ledger.settle_absent(_NONE, _NONE) == 4096
    assert ledger.reserved_mb == 0
    assert ledger.leaked_mb == 0


async def test_a_leak_with_a_create_in_flight_is_not_settled() -> None:
    ledger = WorkspaceMemoryLedger(8192)
    reservation = await ledger.reserve(4096, workspace_id="ws")
    reservation.create_started()
    reservation.leak("exec-1", reason="create abandoned")

    assert ledger.settle_absent(_NONE, _NONE) == 0, "the create may yet make a container"
    reservation.create_ended()
    assert ledger.settle_absent(_NONE, _NONE) == 4096


async def test_a_create_in_flight_when_the_listing_started_blocks_settling() -> None:
    """It ended mid-listing, so the listing may have missed the container it made."""
    ledger = WorkspaceMemoryLedger(8192)
    reservation = await ledger.reserve(4096, workspace_id="ws")
    reservation.leak("exec-1", reason="create abandoned")

    assert ledger.settle_absent(_NONE, frozenset({"ws"})) == 0
    assert ledger.leaked_mb == 4096


async def test_settling_one_leak_leaves_the_listed_one_charged() -> None:
    ledger = WorkspaceMemoryLedger(8192)
    (await ledger.reserve(4096, workspace_id="gone")).leak("exec-1", reason="x")
    (await ledger.reserve(4096, workspace_id="alive")).leak("exec-1", reason="x")

    assert ledger.settle_absent(frozenset({"alive"}), _NONE) == 4096
    assert ledger.leaked() == frozenset({"alive"})


async def test_settling_a_leak_admits_the_waiter_it_was_blocking() -> None:
    ledger = WorkspaceMemoryLedger(4096)
    (await ledger.reserve(4096, workspace_id="ws")).leak("exec-1", reason="x")
    waiter = asyncio.create_task(ledger.reserve(4096, workspace_id="next"))
    await _settle()
    assert not waiter.done()

    ledger.settle_absent(_NONE, _NONE)

    (await asyncio.wait_for(waiter, timeout=1)).release()
