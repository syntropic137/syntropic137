"""Real-Postgres acceptance for the Run Queue (#1310 1.2, ADR-072 V3).

Each test gets its own schema, so a claim sees only the runs that test admitted.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import asyncpg
import pytest

from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    RunLeaseLost,
    StreamPresence,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = pytest.mark.integration


@pytest.fixture
async def pools(test_infrastructure: TestInfrastructure) -> AsyncIterator[list[asyncpg.Pool]]:
    """Four independent pools on one fresh schema (V3: claims across 4 pools)."""
    schema = f"run_queue_{uuid4().hex}"
    admin = await asyncpg.connect(test_infrastructure.timescaledb_url)
    await admin.execute(f"CREATE SCHEMA {schema}")
    created: list[asyncpg.Pool] = []
    try:
        for _ in range(4):
            pool = await asyncpg.create_pool(
                test_infrastructure.timescaledb_url,
                min_size=1,
                max_size=15,
                server_settings={"search_path": schema},
            )
            assert pool is not None
            created.append(pool)
        await PostgresExecutionRunQueue(created[0]).ensure_ready()
        yield created
    finally:
        for pool in created:
            await pool.close()
        await admin.execute(f"DROP SCHEMA {schema} CASCADE")
        await admin.close()


def _host(host_id: str, epoch: int = 1) -> ExecutorHost:
    return ExecutorHost(host_id=host_id, container_id=f"c-{host_id}", generation="g1", epoch=epoch)


async def _online(queue: PostgresExecutionRunQueue, host_id: str, capacity: int) -> None:
    await queue.register(_host(host_id), capacity)
    await queue.heartbeat(host_id)


async def _admit(queue: PostgresExecutionRunQueue, *ids: str, writer_epoch: int = 1) -> None:
    for execution_id in ids:
        assert await queue.reserve(execution_id, writer_epoch, is_resume=False)
        await queue.mark_admitted(execution_id)


async def test_fifty_concurrent_claims_on_one_execution_have_exactly_one_winner(
    pools: list[asyncpg.Pool],
) -> None:
    queues = [PostgresExecutionRunQueue(pool) for pool in pools]
    hosts = [f"host-{i}" for i in range(50)]
    for host in hosts:
        await _online(queues[0], host, capacity=1)
    await _admit(queues[0], "exec-only")

    claims = await asyncio.gather(*(queues[i % 4].claim(host) for i, host in enumerate(hosts)))

    winners = [c for c in claims if c is not None]
    assert [w.execution_id for w in winners] == ["exec-only"]
    async with pools[0].acquire() as conn:
        assert await conn.fetchval("SELECT sum(in_use) FROM execution_budget") == 1
    assert (await queues[0].in_use()).claimed == 1


async def test_budget_two_across_four_pools_admits_exactly_two_and_never_more(
    pools: list[asyncpg.Pool],
) -> None:
    queues = [PostgresExecutionRunQueue(pool) for pool in pools]
    await _online(queues[0], "small-host", capacity=2)
    await _admit(queues[0], *(f"exec-{i:02}" for i in range(20)))

    peak = 0
    samples = 0
    sampling = True

    async def sample() -> None:
        nonlocal peak, samples
        async with pools[3].acquire() as conn:
            while sampling:
                claimed = await conn.fetchval(
                    "SELECT count(*) FROM execution_runs WHERE state='claimed'"
                )
                in_use = await conn.fetchval(
                    "SELECT in_use FROM execution_budget WHERE executor_id='small-host'"
                )
                peak = max(peak, claimed, in_use)
                samples += 1
                await asyncio.sleep(0)

    held: list[ClaimedRun] = []

    async def worker(queue: PostgresExecutionRunQueue) -> None:
        for _ in range(15):
            run = await queue.claim("small-host")
            if run is not None:
                held.append(run)
            if held:
                await queue.close(held.pop(0))

    sampler = asyncio.create_task(sample())
    try:
        first = await asyncio.gather(*(queues[i % 4].claim("small-host") for i in range(20)))
        winners = [c for c in first if c is not None]
        assert len(winners) == 2
        assert len({w.execution_id for w in winners}) == 2

        # Churn: every pool keeps claiming while winners release, sampled throughout.
        held.extend(winners)
        await asyncio.gather(*(worker(q) for q in queues))
    finally:
        # The sampler holds a pool connection; the fixture cannot close the pool under it.
        sampling = False
        await sampler

    assert samples > 0
    assert peak <= 2


async def test_renew_with_a_superseded_token_raises_and_changes_nothing(
    pools: list[asyncpg.Pool],
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _online(queue, "h1", capacity=1)
    await _admit(queue, "exec-renew")
    first = await queue.claim("h1")
    assert first is not None
    await queue.renew(first)

    # Deferral then a fresh claim: the row is claimed again with a live lease,
    # so only the token tells the stale holder apart.
    await queue.defer(first, timedelta(0), "inherited outputs not yet readable")
    second = await queue.claim("h1")
    assert second is not None
    assert second.execution_id == first.execution_id
    assert second.token > first.token

    with pytest.raises(RunLeaseLost):
        await queue.renew(first)
    with pytest.raises(RunLeaseLost):
        await queue.close(first)
    with pytest.raises(RunLeaseLost):
        await queue.defer(first, timedelta(0), "stale")

    async with pools[0].acquire() as conn:
        assert await conn.fetchval("SELECT in_use FROM execution_budget") == 1
    await queue.close(second)
    with pytest.raises(RunLeaseLost):
        await queue.close(second)
    async with pools[0].acquire() as conn:
        assert await conn.fetchval("SELECT in_use FROM execution_budget") == 0


async def test_an_expired_lease_is_never_claimed_and_is_fenced_to_interrupted(
    pools: list[asyncpg.Pool],
) -> None:
    short = PostgresExecutionRunQueue(pools[0], lease_ttl=timedelta(milliseconds=200))
    other = PostgresExecutionRunQueue(pools[1])
    await _online(short, "dying", capacity=1)
    await _online(other, "survivor", capacity=5)
    await _admit(short, "exec-expire")
    held = await short.claim("dying")
    assert held is not None
    await asyncio.sleep(0.5)

    assert await other.claim("survivor") is None
    assert await short.claim("dying") is None
    with pytest.raises(RunLeaseLost):
        await short.renew(held)

    fenced = await other.fence_expired("survivor")
    assert [(f.execution_id, f.executor_id, f.reconciler) for f in fenced] == [
        ("exec-expire", "dying", "survivor")
    ]
    assert await other.fence_expired("survivor") == []
    assert await other.claim("survivor") is None
    with pytest.raises(RunLeaseLost):
        await short.close(held)

    await other.mark_reaped(fenced[0])
    async with pools[0].acquire() as conn:
        assert (
            await conn.fetchval("SELECT in_use FROM execution_budget WHERE executor_id='dying'")
            == 1
        )
    await other.close_interrupted(fenced[0])
    with pytest.raises(RunLeaseLost):
        await other.close_interrupted(fenced[0])
    counts = await other.in_use()
    assert (counts.interrupted, counts.claimed, counts.fencing, counts.reaped) == (1, 0, 0, 0)
    async with pools[0].acquire() as conn:
        assert (
            await conn.fetchval("SELECT in_use FROM execution_budget WHERE executor_id='dying'")
            == 0
        )


async def test_claim_refuses_stale_heartbeat_draining_host_newer_epoch_and_retry_at(
    pools: list[asyncpg.Pool],
) -> None:
    queue = PostgresExecutionRunQueue(pools[0], heartbeat_stale=timedelta(milliseconds=200))
    await _online(queue, "h1", capacity=3)
    await _admit(queue, "newer", writer_epoch=2)
    assert await queue.claim("h1") is None

    await _admit(queue, "readable")
    await asyncio.sleep(0.4)
    assert await queue.claim("h1") is None
    assert await queue.heartbeat("h1") is False
    run = await queue.claim("h1")
    assert run is not None
    assert run.execution_id == "readable"

    await queue.defer(run, timedelta(hours=1), "resume inheritance not readable")
    assert await queue.claim("h1") is None

    async with pools[0].acquire() as conn:
        await conn.execute("UPDATE executor_hosts SET draining=TRUE WHERE host_id='h1'")
    assert await queue.heartbeat("h1") is True
    assert await queue.is_draining("h1") is True

    # A host that has left cannot look alive again.
    await queue.deregister("h1")
    async with pools[0].acquire() as conn:
        before = await conn.fetchval("SELECT heartbeat_at FROM execution_budget")
    with pytest.raises(LookupError):
        await queue.heartbeat("h1")
    async with pools[0].acquire() as conn:
        assert await conn.fetchval("SELECT heartbeat_at FROM execution_budget") == before
    assert await queue.is_draining("h1") is False


async def test_reserve_refuses_a_second_row_and_sweep_never_reads_unknown_as_absent(
    pools: list[asyncpg.Pool],
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    assert await queue.reserve("present", 1, is_resume=False)
    assert not await queue.reserve("present", 1, is_resume=True)
    assert await queue.reserve("absent", 1, is_resume=False)
    assert await queue.reserve("unknown", 1, is_resume=False)

    answers = {
        "present": StreamPresence.PRESENT,
        "absent": StreamPresence.ABSENT,
        "unknown": StreamPresence.UNKNOWN,
    }

    class Probe:
        async def presence(self, execution_id: str) -> StreamPresence:
            return answers[execution_id]

    swept = await queue.sweep_opening(timedelta(0), Probe())
    assert swept.admitted == ("present",)
    assert swept.abandoned == ("absent",)
    counts = await queue.in_use()
    assert (counts.admitted, counts.abandoned, counts.opening) == (1, 1, 1)

    # abandoned is provisional: a late open promotes it, and reserve still refuses.
    answers["absent"] = StreamPresence.PRESENT
    swept = await queue.sweep_opening(timedelta(0), Probe())
    assert swept.admitted == ("absent",)
    assert not await queue.reserve("absent", 1, is_resume=False)


async def test_schema_is_idempotent_and_keeps_rows(pools: list[asyncpg.Pool]) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _admit(queue, "kept")
    await queue.ensure_ready()
    assert (await queue.in_use()).admitted == 1
