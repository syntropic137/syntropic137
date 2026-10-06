"""Real SQL: status transitions remain durable without growing on every poll."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.child_journal import child_read_status
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_domain.contexts.agent_sessions import (
    EvidenceBatch,
    InventoryPublicationConflict,
    PendingEvidence,
    RunIdentity,
)

if TYPE_CHECKING:
    import asyncpg

    from syn_domain.contexts.agent_sessions import AcquisitionStatusEvidence

pytestmark = pytest.mark.integration


async def _fence(db_pool: asyncpg.Pool, run: RunIdentity) -> tuple[int, AcquisitionStatusEvidence]:
    """The run's single acquisition head: the journal sequence it points at, and its status."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT evidence_sequence::text AS sequence,payload::text
            FROM session_acquisition_heads WHERE source_instance_id=$1 AND execution_id=$2""",
            run.source_instance_id,
            run.execution_id,
        )
    assert len(rows) == 1
    batch = EvidenceBatch.model_validate_json(rows[0]["payload"])
    return int(rows[0]["sequence"]), batch.evidence.acquisition_statuses[0]


async def test_unchanged_polls_remain_bounded_across_restart_and_stale_failure(db_pool):
    journal = PostgresSessionEvidence(db_pool)
    await journal.ensure_ready()
    run = RunIdentity(source_instance_id=str(uuid4()), execution_id="run")
    for sequence in range(1, 101):
        assert (
            await journal.observe_acquisition(
                child_read_status(run, "spool", sequence, failed=False)
            )
            == 1
        )
    await journal.acknowledge_dispatch(PendingEvidence(run=run, watermark=1))
    assert all(item.run != run for item in await journal.pending())
    assert await journal.observe_acquisition(child_read_status(run, "spool", 103, failed=True)) == 2
    assert await journal.observe_acquisition(child_read_status(run, "spool", 104, failed=True)) == 2
    assert (
        await journal.observe_acquisition(child_read_status(run, "spool", 105, failed=False)) == 3
    )
    restarted = PostgresSessionEvidence(db_pool)
    assert (
        await restarted.observe_acquisition(child_read_status(run, "spool", 106, failed=False)) == 3
    )
    assert (
        await restarted.observe_acquisition(child_read_status(run, "spool", 102, failed=True)) == 3
    )
    with pytest.raises(InventoryPublicationConflict, match="sequence reused"):
        await restarted.observe_acquisition(child_read_status(run, "spool", 106, failed=True))
    assert await journal.watermark(run) == 3
    page = await journal.read(run, 3)
    assert [
        (
            b.batch.evidence.acquisition_statuses[0].sequence,
            b.batch.evidence.acquisition_statuses[0].failed,
        )
        for b in page.items
    ] == [(1, False), (103, True), (105, False)]
    async with db_pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM session_acquisition_heads WHERE source_instance_id=$1",
                run.source_instance_id,
            )
            == 1
        )


async def test_legacy_history_seeds_checkpoint_without_rewriting_evidence(db_pool):
    journal = PostgresSessionEvidence(db_pool)
    await journal.ensure_ready()
    run = RunIdentity(source_instance_id=str(uuid4()), execution_id="run")
    old = child_read_status(run, "spool", 20, failed=True)
    await journal.append(old)
    before = await journal.read(run, 1)
    assert await journal.observe_acquisition(child_read_status(run, "spool", 19, failed=False)) == 1
    assert await journal.observe_acquisition(child_read_status(run, "spool", 21, failed=True)) == 1
    assert await journal.observe_acquisition(child_read_status(run, "spool", 22, failed=False)) == 2
    assert await journal.read(run, 1) == before
    assert (
        await journal.observe_acquisition(child_read_status(run, "other-spool", 1, failed=False))
        == 3
    )
    assert await journal.watermark(run) == 3


async def test_concurrent_observations_keep_highest_sequence_fence(db_pool):
    journal = PostgresSessionEvidence(db_pool)
    await journal.ensure_ready()
    run = RunIdentity(source_instance_id=str(uuid4()), execution_id="run")
    await asyncio.gather(
        *(
            journal.observe_acquisition(
                child_read_status(run, "spool", sequence, failed=sequence % 2 == 1)
            )
            for sequence in reversed(range(1, 31))
        )
    )
    # Lock order is not arrival order, and a same-state observation appends no
    # batch, so the journal's newest batch may be any healthy sequence (#1639).
    # The fence is what must reach 30, pointing at the newest batch.
    watermark = await journal.watermark(run)
    newest = (await journal.read(run, watermark)).items[-1]
    fence_sequence, fence = await _fence(db_pool, run)
    assert (fence.sequence, fence.failed) == (30, False)
    assert fence_sequence == newest.sequence == watermark
    assert newest.batch.evidence.acquisition_statuses[0].failed is False
    assert (
        await journal.observe_acquisition(child_read_status(run, "spool", 29, failed=True))
        == watermark
    )
    assert (
        await journal.observe_acquisition(child_read_status(run, "spool", 31, failed=False))
        == watermark
    )



async def test_same_state_newer_sequence_moves_fence_without_journal_batch(db_pool):
    """The ordering behind #1639: a healthy 24 locks first, then a healthy 30."""
    journal = PostgresSessionEvidence(db_pool)
    await journal.ensure_ready()
    run = RunIdentity(source_instance_id=str(uuid4()), execution_id="run")
    assert await journal.observe_acquisition(child_read_status(run, "spool", 24, failed=False)) == 1
    assert await journal.observe_acquisition(child_read_status(run, "spool", 30, failed=False)) == 1
    page = await journal.read(run, await journal.watermark(run))
    assert [item.batch.evidence.acquisition_statuses[0].sequence for item in page.items] == [24]
    fence_sequence, fence = await _fence(db_pool, run)
    assert (fence_sequence, fence.sequence, fence.failed) == (1, 30, False)
    assert await journal.observe_acquisition(child_read_status(run, "spool", 29, failed=True)) == 1
    assert (await _fence(db_pool, run))[1].sequence == 30
