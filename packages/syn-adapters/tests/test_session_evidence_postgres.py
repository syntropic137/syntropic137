"""Real SQL journal/outbox tests, including arrivals during reconciliation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_domain.contexts.agent_sessions import (
    EvidenceBatch,
    InventoryPublicationConflict,
    PendingEvidence,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import SessionEvidence

if TYPE_CHECKING:
    import asyncpg

pytestmark = pytest.mark.integration


@pytest.fixture
async def journal(db_pool: asyncpg.Pool) -> PostgresSessionEvidence:
    store = PostgresSessionEvidence(db_pool)
    await store.ensure_ready()
    return store


@pytest.fixture
def run() -> RunIdentity:
    return RunIdentity(source_instance_id=f"evidence-test-{uuid4()}", execution_id="run")


def batch(run: RunIdentity, name: str) -> EvidenceBatch:
    return EvidenceBatch(batch_id=name, producer_id="host", evidence=SessionEvidence(run=run))


async def test_duplicate_receipts_do_not_advance_watermark_but_changed_payload_fails(
    journal: PostgresSessionEvidence,
    run: RunIdentity,
) -> None:
    original = batch(run, "receipt-1")
    assert await journal.append(original) == 1
    assert await journal.append(original) == 1
    assert await journal.watermark(run) == 1
    # Same record identity with different coverage is not an idempotent redelivery.
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        CoverageContract,
    )

    changed = original.model_copy(
        update={
            "evidence": SessionEvidence(
                run=run,
                coverage_contract=CoverageContract(contract_id="host/1", expected_nodes=()),
            )
        }
    )
    with pytest.raises(InventoryPublicationConflict):
        await journal.append(changed)
    assert await journal.watermark(run) == 1


async def test_late_arrival_stays_pending_after_older_dispatch_acknowledgement(
    journal: PostgresSessionEvidence,
    db_pool: asyncpg.Pool,
    run: RunIdentity,
) -> None:
    await journal.append(batch(run, "first"))
    pending = PendingEvidence(run=run, watermark=1)
    assert pending in await journal.pending()
    await journal.append(batch(run, "late"))
    await journal.acknowledge_dispatch(pending)
    await db_pool.expire_connections()
    restarted = PostgresSessionEvidence(db_pool)
    newer = PendingEvidence(run=run, watermark=2)
    assert newer in await restarted.pending()
    assert (await restarted.read(run, 1)).items[0].batch.batch_id == "first"
    assert len((await restarted.read(run, 1)).items) == 1
    await restarted.acknowledge_dispatch(newer)
    await restarted.acknowledge_dispatch(pending)
    assert not any(item.run == run for item in await restarted.pending())


async def test_concurrent_appends_have_contiguous_committed_sequence_and_bounded_pages(
    journal: PostgresSessionEvidence,
    run: RunIdentity,
) -> None:
    results = await asyncio.gather(*(journal.append(batch(run, str(n))) for n in range(23)))
    assert sorted(results) == list(range(1, 24))
    watermark = await journal.watermark(run)
    first = await journal.read(run, watermark, limit=10)
    assert first.next_after == 10
    assert [item.sequence for item in first.items] == list(range(1, 11))
    await journal.append(batch(run, "future"))
    second = await journal.read(run, watermark, after=first.next_after, limit=10)
    assert second.next_after == 20
    third = await journal.read(run, watermark, after=20, limit=10)
    assert [item.sequence for item in third.items] == [21, 22, 23]
    assert third.next_after is None


async def test_uncommitted_watermarks_and_foreign_scope_are_rejected(
    journal: PostgresSessionEvidence,
    run: RunIdentity,
) -> None:
    await journal.append(batch(run, "first"))
    with pytest.raises(ValueError, match="uncommitted"):
        await journal.read(run, 2)
    with pytest.raises(ValueError, match="not committed"):
        await journal.acknowledge_dispatch(PendingEvidence(run=run, watermark=2))
    foreign = run.model_copy(update={"source_instance_id": "other"})
    assert await journal.watermark(foreign) == 0
    with pytest.raises(ValueError):
        await journal.read(foreign, 1)
