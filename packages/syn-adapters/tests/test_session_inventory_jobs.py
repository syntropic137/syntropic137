"""Real database leases prevent expired workers from publishing inventory."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.postgres_inventory import PostgresSessionInventory
from syn_adapters.session_inventory.postgres_jobs import PostgresSessionInventoryJobs
from syn_domain.contexts.agent_sessions import (
    InventoryCounts,
    InventoryCoverage,
    InventoryJob,
    InventoryLeaseLost,
    InventorySnapshot,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
    ReconciliationStage,
    ReconciliationState,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import CoverageState

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

pytestmark = pytest.mark.integration


@pytest.fixture
async def job(db_pool: asyncpg.Pool) -> AsyncIterator[InventoryJob]:
    run = RunIdentity(source_instance_id=f"lease-{uuid4()}", execution_id="run")
    item = InventoryJob(
        job_id=str(uuid4()),
        global_position=1,
        state=ReconciliationState(
            request=ReconciliationRequest(
                run=run,
                evidence_watermark=0,
                expected_head=None,
                snapshot_id=uuid4(),
                resolver_version="test/1",
            )
        ),
    )
    store = PostgresSessionInventoryJobs(db_pool)
    await store.ensure_ready()
    await store.project(item)
    yield item
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM session_inventory_jobs WHERE job_id=$1", item.job_id)


async def test_only_one_worker_claims_and_replay_does_not_revoke_lease(
    db_pool: asyncpg.Pool,
    job: InventoryJob,
) -> None:
    store = PostgresSessionInventoryJobs(db_pool)
    leases = await asyncio.gather(store.claim(lease_seconds=60), store.claim(lease_seconds=60))
    claimed = [lease for lease in leases if lease is not None]
    assert len(claimed) == 1
    await store.project(job)
    await store.renew(claimed[0], lease_seconds=60)
    assert await store.latest(job.state.request.run) == job


async def test_expired_worker_cannot_renew_release_or_publish_new_owners_lease(
    db_pool: asyncpg.Pool,
    job: InventoryJob,
) -> None:
    store = PostgresSessionInventoryJobs(db_pool)
    old = await store.claim(lease_seconds=60)
    assert old is not None
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_inventory_jobs SET leased_until=now()-interval '1 second' WHERE job_id=$1",
            job.job_id,
        )
    with pytest.raises(InventoryLeaseLost):
        await store.renew(old, lease_seconds=60)
    newer = await store.claim(lease_seconds=60)
    assert newer is not None
    assert newer.token > old.token
    await store.release(old, retry_seconds=100)
    await store.renew(newer, lease_seconds=60)
    with pytest.raises(InventoryLeaseLost):
        await store.publish(old)


async def test_new_projected_step_invalidates_old_claim_and_ignores_stale_replay(
    db_pool: asyncpg.Pool,
    job: InventoryJob,
) -> None:
    store = PostgresSessionInventoryJobs(db_pool)
    old = await store.claim(lease_seconds=60)
    assert old is not None
    publishing = job.model_copy(
        update={
            "global_position": 2,
            "state": job.state.model_copy(
                update={"stage": ReconciliationStage.PUBLISHING, "revision": "r1"}
            ),
        }
    )
    await store.project(publishing)
    await store.project(job)
    assert await store.get(job.job_id) == publishing
    with pytest.raises(InventoryLeaseLost):
        await store.renew(old, lease_seconds=60)
    current = await store.claim(lease_seconds=60)
    assert current is not None
    assert current.job == publishing


async def test_publication_checks_lease_and_inventory_head_in_one_transaction(
    db_pool: asyncpg.Pool,
    job: InventoryJob,
) -> None:
    store = PostgresSessionInventoryJobs(db_pool)
    inventory = PostgresSessionInventory(db_pool)
    publishing = job.model_copy(
        update={
            "global_position": 2,
            "state": job.state.model_copy(
                update={"stage": ReconciliationStage.PUBLISHING, "revision": "r1"}
            ),
        }
    )
    await store.project(publishing)
    request = job.state.request
    snapshot = InventorySnapshot(
        snapshot_id=request.snapshot_id,
        run=request.run,
        evidence_watermark=0,
        revision="r1",
        resolver_version="test/1",
        coverage=InventoryCoverage(state=CoverageState.UNKNOWN),
        counts=InventoryCounts(node=0, membership=0, edge=0, capture=0, gap=0, namespaces=()),
    )
    await inventory.stage(snapshot)
    lease = await store.claim(lease_seconds=60)
    assert lease is not None
    await store.publish(lease)
    await store.publish(lease)
    assert await inventory.head(request.run) == snapshot
    await store.release(lease, retry_seconds=0)
    with pytest.raises(InventoryLeaseLost):
        await store.publish(lease)


async def test_job_prefix_lookup_is_literal_bounded_and_source_scoped(
    db_pool: asyncpg.Pool, job: InventoryJob
) -> None:
    store = PostgresSessionInventoryJobs(db_pool)
    source = job.state.request.run.source_instance_id
    assert await store.find_ids(source, job.job_id[:8]) == (job.job_id,)
    assert await store.find_ids(source, job.job_id) == (job.job_id,)
    assert await store.find_ids("other-installation", job.job_id[:8]) == ()
    for literal in ("%", "_", "\\", job.job_id[:8] + "%"):
        assert await store.find_ids(source, literal) == ()
    assert await store.find_ids(source, "") == ()
    assert await store.find_ids(source, "x" * 37) == ()
    siblings = [job.model_copy(update={"job_id": f"{job.job_id[:8]}-{i}"}) for i in range(3)]
    try:
        for sibling in siblings:
            await store.project(sibling)
        assert len(await store.find_ids(source, job.job_id[:8])) == 2
        assert await store.find_ids(source, job.job_id) == (job.job_id,)
    finally:
        async with db_pool.acquire() as conn:
            for sibling in siblings:
                await conn.execute(
                    "DELETE FROM session_inventory_jobs WHERE job_id=$1", sibling.job_id
                )
