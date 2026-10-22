"""Real-Postgres acceptance for the Run Queue (#1310 1.2, ADR-072 V3).

Each test gets its own schema, so a claim sees only the runs that test admitted.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import asyncpg
import pytest

from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_domain.contexts.orchestration.ports import (
    Capability,
    ClaimedRun,
    ExecutorHost,
    ExecutorPool,
    PoolDefinitionConflict,
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
    return ExecutorHost(
        host_id=host_id,
        container_id=f"c-{host_id}",
        generation="g1",
        epoch=epoch,
        reap_scope="engine-1",
    )


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

    fenced = await other.fence_expired("survivor", limit=10)
    assert [(f.execution_id, f.executor_id, f.reconciler) for f in fenced] == [
        ("exec-expire", "dying", "survivor")
    ]
    assert await other.fence_expired("survivor", limit=10) == []
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


async def test_fence_leaves_a_live_lease_alone(pools: list[asyncpg.Pool]) -> None:
    """D5: only an expired lease is fenced. Fencing a live one would kill a healthy run."""
    queue = PostgresExecutionRunQueue(pools[0])
    reconciler = PostgresExecutionRunQueue(pools[1])
    await _online(queue, "h1", capacity=1)
    await _online(reconciler, "rec", capacity=1)
    await _admit(queue, "live")
    run = await queue.claim("h1")
    assert run is not None

    assert await reconciler.fence_expired("rec", limit=10) == []
    assert (await queue.in_use()).claimed == 1
    await queue.renew(run)
    await queue.close(run)


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

    # Eligible work, room and a fresh heartbeat: only draining stands in the way.
    await _admit(queue, "eligible")
    async with pools[0].acquire() as conn:
        await conn.execute("UPDATE executor_hosts SET draining=TRUE WHERE host_id='h1'")
    assert await queue.heartbeat("h1") is True
    assert await queue.is_draining("h1") is True
    assert await queue.claim("h1") is None
    async with pools[0].acquire() as conn:
        assert await conn.fetchval("SELECT in_use FROM execution_budget") == 0
        assert (
            await conn.fetchval("SELECT state FROM execution_runs WHERE execution_id='eligible'")
            == "admitted"
        )

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


async def _blocked_until_waiting(pool: asyncpg.Pool, fragment: str) -> None:
    """Return once a statement containing ``fragment`` is waiting on a row lock."""
    for _ in range(200):
        async with pool.acquire() as conn:
            if await conn.fetchval(
                """SELECT count(*) FROM pg_stat_activity
                WHERE wait_event_type='Lock' AND query LIKE '%' || $1 || '%'""",
                fragment,
            ):
                return
        await asyncio.sleep(0.01)
    raise AssertionError(f"no statement containing {fragment!r} reached its lock")


async def test_claim_that_waits_out_its_heartbeat_on_the_budget_lock_gets_nothing(
    pools: list[asyncpg.Pool],
) -> None:
    ttl = timedelta(milliseconds=200)
    queue = PostgresExecutionRunQueue(pools[0], lease_ttl=ttl, heartbeat_stale=ttl)
    await _online(queue, "slow", capacity=1)
    await _admit(queue, "work")
    async with pools[1].acquire() as blocker, blocker.transaction():
        await blocker.execute("SELECT 1 FROM execution_budget WHERE executor_id='slow' FOR UPDATE")
        claim = asyncio.create_task(queue.claim("slow"))
        await _blocked_until_waiting(pools[2], "execution_budget")
        await asyncio.sleep(0.4)
    assert await claim is None
    assert (await queue.in_use()).admitted == 1


async def test_claim_whose_heartbeat_is_refreshed_during_the_wait_gets_a_full_lease(
    pools: list[asyncpg.Pool],
) -> None:
    ttl = timedelta(milliseconds=300)
    queue = PostgresExecutionRunQueue(pools[0], lease_ttl=ttl, heartbeat_stale=ttl)
    await _online(queue, "slow", capacity=1)
    await _admit(queue, "work")
    async with pools[1].acquire() as blocker, blocker.transaction():
        await blocker.execute("SELECT 1 FROM execution_budget WHERE executor_id='slow' FOR UPDATE")
        claim = asyncio.create_task(queue.claim("slow"))
        await _blocked_until_waiting(pools[2], "execution_budget")
        await asyncio.sleep(0.5)
        await blocker.execute(
            "UPDATE execution_budget SET heartbeat_at=clock_timestamp() WHERE executor_id='slow'"
        )
    run = await claim
    assert run is not None
    async with pools[2].acquire() as conn:
        remaining = await conn.fetchval(
            """SELECT extract(epoch FROM leased_until-clock_timestamp())
            FROM execution_runs WHERE execution_id='work'"""
        )
    assert remaining > 0.2


async def test_renew_that_waits_out_its_lease_on_the_run_lock_raises(
    pools: list[asyncpg.Pool],
) -> None:
    queue = PostgresExecutionRunQueue(pools[0], lease_ttl=timedelta(milliseconds=200))
    await _online(queue, "h1", capacity=1)
    await _admit(queue, "work")
    run = await queue.claim("h1")
    assert run is not None
    async with pools[1].acquire() as blocker, blocker.transaction():
        await blocker.execute("SELECT 1 FROM execution_runs WHERE execution_id='work' FOR UPDATE")
        renew = asyncio.create_task(queue.renew(run))
        await _blocked_until_waiting(pools[2], "execution_runs")
        await asyncio.sleep(0.4)
    with pytest.raises(RunLeaseLost):
        await renew


async def test_defer_that_waits_on_the_budget_lock_keeps_its_full_backoff(
    pools: list[asyncpg.Pool],
) -> None:
    """``retry_at`` is set after the release's locks, so a lock wait cannot spend the backoff."""
    queue = PostgresExecutionRunQueue(pools[0])
    other = PostgresExecutionRunQueue(pools[3])
    await _online(queue, "h1", capacity=1)
    await _online(other, "h2", capacity=1)
    await _admit(queue, "work")
    run = await queue.claim("h1")
    assert run is not None
    async with pools[1].acquire() as blocker, blocker.transaction():
        await blocker.execute("SELECT 1 FROM execution_budget WHERE executor_id='h1' FOR UPDATE")
        defer = asyncio.create_task(queue.defer(run, timedelta(milliseconds=300), "not readable"))
        await _blocked_until_waiting(pools[2], "in_use=in_use-1")
        await asyncio.sleep(0.5)
    await defer
    assert await other.claim("h2") is None
    async with pools[2].acquire() as conn:
        remaining = await conn.fetchval(
            """SELECT extract(epoch FROM retry_at-clock_timestamp())
            FROM execution_runs WHERE execution_id='work'"""
        )
    assert remaining > 0.1


@pytest.mark.parametrize("left_at", ["fencing", "reaped"])
async def test_a_reconcilers_rows_are_taken_over_only_after_it_leaves(
    pools: list[asyncpg.Pool], left_at: str
) -> None:
    """D5: a reconciler's rows are durable. Its successor finds them in the queue,
    never in memory, and adopts them only once the old owner's host row is gone."""
    short = PostgresExecutionRunQueue(pools[0], lease_ttl=timedelta(milliseconds=200))
    first = PostgresExecutionRunQueue(pools[1])
    successor = PostgresExecutionRunQueue(pools[2])
    await _online(short, "dying", capacity=1)
    await _online(first, "rec-1", capacity=1)
    await _online(successor, "rec-2", capacity=1)
    await _admit(short, "exec-adopt")
    assert await short.claim("dying") is not None
    await asyncio.sleep(0.5)
    (fenced,) = await first.fence_expired("rec-1", limit=10)
    if left_at == "reaped":
        await first.mark_reaped(fenced)

    # A fresh reconciler object for the same host rediscovers its own row.
    (mine,) = await PostgresExecutionRunQueue(pools[3]).reconciling("rec-1")
    assert (mine.token, mine.reaped) == (fenced.token, left_at == "reaped")
    # rec-1 is still registered, however stale: no takeover.
    assert await successor.take_over("rec-2", limit=10) == []

    await first.deregister("rec-1")
    assert await successor.reconciling("rec-2") == []  # reading adopts nothing
    (adopted,) = await successor.take_over("rec-2", limit=10)
    assert (adopted.reconciler, adopted.executor_id) == ("rec-2", "dying")
    assert adopted.token > fenced.token
    assert adopted.reaped == (left_at == "reaped")
    # The old owner's writes are fenced by the new token.
    with pytest.raises(RunLeaseLost):
        await (
            first.close_interrupted(fenced) if left_at == "reaped" else first.mark_reaped(fenced)
        )

    if not adopted.reaped:
        await successor.mark_reaped(adopted)
    await successor.close_interrupted(adopted)
    assert await successor.reconciling("rec-2") == []
    counts = await successor.in_use()
    assert (counts.interrupted, counts.fencing, counts.reaped) == (1, 0, 0)
    async with pools[0].acquire() as conn:
        assert (
            await conn.fetchval("SELECT in_use FROM execution_budget WHERE executor_id='dying'")
            == 0
        )


async def test_a_restart_in_the_same_container_retires_the_predecessor_not_its_work(
    pools: list[asyncpg.Pool],
) -> None:
    """D5 Restart: the new process gets a new host_id, deletes the old one's host
    row, and fences the old one's expired run as the OLD host's (so the reap
    selects the predecessor's containers, never the successor's)."""
    old = PostgresExecutionRunQueue(pools[0], lease_ttl=timedelta(milliseconds=200))
    new = PostgresExecutionRunQueue(pools[1])
    box = "container-1"
    await old.register(
        ExecutorHost(
            host_id="box.aaa", container_id=box, generation="g", epoch=1, reap_scope="engine-1"
        ),
        1,
    )
    await old.heartbeat("box.aaa")
    await _admit(old, "exec-before-restart")
    assert await old.claim("box.aaa") is not None
    await asyncio.sleep(0.5)

    await new.register(
        ExecutorHost(
            host_id="box.bbb", container_id=box, generation="g", epoch=1, reap_scope="engine-1"
        ),
        1,
    )
    await new.heartbeat("box.bbb")
    async with pools[0].acquire() as conn:
        hosts = await conn.fetch("SELECT host_id FROM executor_hosts")
        assert [row["host_id"] for row in hosts] == ["box.bbb"]
    with pytest.raises(LookupError):
        await old.heartbeat("box.aaa")

    (fenced,) = await new.fence_expired("box.bbb", limit=10)
    assert (fenced.executor_id, fenced.reconciler) == ("box.aaa", "box.bbb")


async def _machine(pools: list[asyncpg.Pool], box: str) -> tuple[int, dict[str, tuple[int, int]]]:
    async with pools[0].acquire() as conn:
        rows = await conn.fetch(
            "SELECT executor_id,capacity,in_use FROM execution_budget WHERE container_id=$1",
            box,
        )
    budgets = {row["executor_id"]: (row["capacity"], row["in_use"]) for row in rows}
    return sum(capacity for capacity, _ in budgets.values()), budgets


async def test_a_restart_transfers_the_machine_budget_and_never_doubles_it(
    pools: list[asyncpg.Pool],
) -> None:
    """D3 Restart (R1): a capacity-one machine whose old process still holds an
    unexpired run cannot claim a second one after a restart. The slot moves to
    the successor when the old run is closed, exactly once."""
    old = PostgresExecutionRunQueue(pools[0], lease_ttl=timedelta(milliseconds=300))
    new = PostgresExecutionRunQueue(pools[1], lease_ttl=timedelta(milliseconds=300))
    box = "container-r1"
    await old.register(
        ExecutorHost(
            host_id="r1.aaa", container_id=box, generation="g", epoch=1, reap_scope="engine-1"
        ),
        1,
    )
    await old.heartbeat("r1.aaa")
    await _admit(old, "exec-held", "exec-waiting")
    held = await old.claim("r1.aaa")
    assert held is not None

    await new.register(
        ExecutorHost(
            host_id="r1.bbb", container_id=box, generation="g", epoch=1, reap_scope="engine-1"
        ),
        1,
    )
    await new.heartbeat("r1.bbb")
    assert await _machine(pools, box) == (1, {"r1.aaa": (1, 1), "r1.bbb": (0, 0)})
    assert await new.claim("r1.bbb") is None

    await asyncio.sleep(0.5)
    (fenced,) = await new.fence_expired("r1.bbb", limit=10)
    await new.mark_reaped(fenced)
    await new.close_interrupted(fenced)
    assert await _machine(pools, box) == (1, {"r1.aaa": (0, 0), "r1.bbb": (1, 0)})
    # Neither a duplicate close nor the stale owner's terminal commit moves a slot.
    with pytest.raises(RunLeaseLost):
        await new.close_interrupted(fenced)
    with pytest.raises(RunLeaseLost):
        await old.close(held)
    assert await _machine(pools, box) == (1, {"r1.aaa": (0, 0), "r1.bbb": (1, 0)})

    claimed = await new.claim("r1.bbb")
    assert claimed is not None and claimed.execution_id == "exec-waiting"
    assert await new.claim("r1.bbb") is None
    await new.close(claimed)
    assert await _machine(pools, box) == (1, {"r1.aaa": (0, 0), "r1.bbb": (1, 0)})


# --- Executor Pools (ADR-072 D13, placement plan PR 1) ---------------------------

_P1 = ExecutorPool(pool_id="p1", priority=1, provider="docker", region="eu-west")


def _in_pool(host_id: str, pool: ExecutorPool, *, container_id: str | None = None) -> ExecutorHost:
    return ExecutorHost(
        host_id=host_id,
        container_id=container_id or f"c-{host_id}",
        generation="g1",
        epoch=1,
        reap_scope="engine-1",
        pool=pool,
    )


async def _pool_row(conn: asyncpg.Connection, pool_id: str) -> tuple[object, ...]:
    row = await conn.fetchrow(
        """SELECT priority,provider,region,isolation,capabilities,overflow_delay_s
        FROM executor_pools WHERE pool_id=$1""",
        pool_id,
    )
    assert row is not None
    return tuple(row)


async def test_a_second_member_declaring_a_different_pool_definition_is_refused_and_writes_nothing(
    pools: list[asyncpg.Pool],
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    # A has registered and not yet beaten: it is a member all the same.
    await queue.register(_in_pool("a", _P1), 2)
    # B starts in X's container, so a committed B would have retired X.
    await _online(queue, "x", 3)
    redefined = _P1.model_copy(update={"priority": 5, "capabilities": frozenset(Capability)})

    with pytest.raises(PoolDefinitionConflict, match="'p1'"):
        await queue.register(_in_pool("b", redefined, container_id="c-x"), 2)

    async with pools[0].acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM executor_hosts WHERE host_id='b'") == 0
        assert (
            await conn.fetchval("SELECT count(*) FROM execution_budget WHERE executor_id='b'") == 0
        )
        assert await conn.fetchval("SELECT count(*) FROM executor_hosts WHERE host_id='x'") == 1
        assert (
            await conn.fetchval("SELECT capacity FROM execution_budget WHERE executor_id='x'") == 3
        )
        assert await _pool_row(conn, "p1") == (1, "docker", "eu-west", 10, [], 60)


async def test_a_sole_member_restarting_in_its_container_may_redefine_its_pool(
    pools: list[asyncpg.Pool],
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await queue.register(_in_pool("a.1", _P1, container_id="box"), 2)
    await queue.heartbeat("a.1")
    redefined = ExecutorPool(
        pool_id="p1",
        priority=3,
        provider="docker",
        capabilities=frozenset({Capability.NESTED_DOCKER}),
        overflow_delay=timedelta(seconds=15),
    )

    await queue.register(_in_pool("a.2", redefined, container_id="box"), 2)

    async with pools[0].acquire() as conn:
        assert await _pool_row(conn, "p1") == (3, "docker", None, 10, ["nested_docker"], 15)
        assert (
            await conn.fetchval("SELECT pool_id FROM execution_budget WHERE executor_id='a.2'")
            == "p1"
        )
    # The stored definition now equals the declaration: re-registering is a no-op.
    await queue.register(_in_pool("a.2", redefined, container_id="box"), 2)


async def test_a_member_may_redefine_its_pool_once_every_other_member_is_draining(
    pools: list[asyncpg.Pool],
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    for host_id in ("a", "b"):
        await queue.register(_in_pool(host_id, _P1), 1)
        await queue.heartbeat(host_id)
    redefined = _P1.model_copy(update={"region": None})

    async with pools[0].acquire() as conn:
        await conn.execute("UPDATE executor_hosts SET draining=TRUE WHERE host_id='a'")
    with pytest.raises(PoolDefinitionConflict):
        await queue.register(_in_pool("c", redefined), 1)

    async with pools[0].acquire() as conn:
        await conn.execute("UPDATE executor_hosts SET draining=TRUE WHERE host_id='b'")
    await queue.register(_in_pool("c", redefined), 1)
    async with pools[0].acquire() as conn:
        assert (await _pool_row(conn, "p1"))[2] is None


async def test_a_member_that_is_no_longer_live_does_not_hold_its_pools_definition(
    pools: list[asyncpg.Pool],
) -> None:
    """A crashed member keeps its host row until reconciled; it must not pin the pool."""
    queue = PostgresExecutionRunQueue(pools[0], heartbeat_stale=timedelta(seconds=30))
    await queue.register(_in_pool("a", _P1), 1)
    await queue.heartbeat("a")
    async with pools[0].acquire() as conn:
        await conn.execute(
            "UPDATE executor_hosts SET registered_at=now()-interval '1 minute' WHERE host_id='a'"
        )
        await conn.execute(
            "UPDATE execution_budget SET heartbeat_at=now()-interval '1 minute' WHERE executor_id='a'"
        )

    await queue.register(_in_pool("b", _P1.model_copy(update={"priority": 7})), 1)
    async with pools[0].acquire() as conn:
        assert (await _pool_row(conn, "p1"))[0] == 7


async def test_a_registration_that_waits_on_the_pool_lock_is_live_when_it_commits(
    pools: list[asyncpg.Pool],
) -> None:
    """Until its first heartbeat a member's registration is its liveness.

    now() is the transaction's start, so a registration that waited out the
    staleness window on a lock must not commit already stale.
    """
    queue = PostgresExecutionRunQueue(pools[0], heartbeat_stale=timedelta(seconds=1))
    joining: asyncio.Task[None] | None = None
    try:
        async with pools[1].acquire() as blocker, blocker.transaction():
            await blocker.execute("SELECT 1 FROM executor_pools WHERE pool_id='default' FOR UPDATE")
            joining = asyncio.create_task(queue.register(_host("fresh-after-wait"), 1))
            await _blocked_until_waiting(pools[2], "FROM executor_pools")
            await asyncio.sleep(1.2)
        await joining

        competing = ExecutorPool(pool_id="default", priority=1, provider="docker")
        with pytest.raises(PoolDefinitionConflict):
            await queue.register(_in_pool("conflicting-after-wait", competing), 1)
    finally:
        if joining is not None:
            if not joining.done():
                joining.cancel()
            await asyncio.gather(joining, return_exceptions=True)


async def test_a_restart_that_waits_on_its_predecessors_budget_lock_is_live_when_it_commits(
    pools: list[asyncpg.Pool],
) -> None:
    """The same rule for the budget lock D3 Restart takes on the predecessor's row."""
    queue = PostgresExecutionRunQueue(pools[0], heartbeat_stale=timedelta(seconds=1))
    await queue.register(_in_pool("a.1", _P1, container_id="box"), 1)
    joining: asyncio.Task[None] | None = None
    try:
        async with pools[1].acquire() as blocker, blocker.transaction():
            await blocker.execute(
                "SELECT 1 FROM execution_budget WHERE executor_id='a.1' FOR UPDATE"
            )
            joining = asyncio.create_task(
                queue.register(_in_pool("a.2", _P1, container_id="box"), 1)
            )
            await _blocked_until_waiting(pools[2], "FROM execution_budget")
            await asyncio.sleep(1.2)
        await joining

        with pytest.raises(PoolDefinitionConflict):
            await queue.register(_in_pool("b", _P1.model_copy(update={"priority": 7})), 1)
    finally:
        if joining is not None:
            if not joining.done():
                joining.cancel()
            await asyncio.gather(joining, return_exceptions=True)


async def test_a_restart_that_changes_pool_moves_the_machines_free_capacity_to_the_new_row(
    pools: list[asyncpg.Pool],
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    box = "container-move"
    await queue.register(
        ExecutorHost(
            host_id="m.1", container_id=box, generation="g", epoch=1, reap_scope="engine-1"
        ),
        3,
    )
    await queue.heartbeat("m.1")
    await _admit(queue, "exec-held")
    assert await queue.claim("m.1") is not None

    await queue.register(_in_pool("m.2", _P1, container_id=box), 3)

    assert await _machine(pools, box) == (3, {"m.1": (1, 1), "m.2": (2, 0)})
    async with pools[0].acquire() as conn:
        rows = await conn.fetch(
            "SELECT executor_id,pool_id FROM execution_budget WHERE container_id=$1", box
        )
    assert {row["executor_id"]: row["pool_id"] for row in rows} == {"m.1": "default", "m.2": "p1"}


_PRE_POOL_SCHEMA = Path(__file__).parent / "fixtures" / "execution_runs" / "schema_pre_pool.sql"


@pytest.fixture
async def pre_pool(test_infrastructure: TestInfrastructure) -> AsyncIterator[asyncpg.Pool]:
    """One pool on a fresh schema holding the frozen pre-pool Run Queue tables."""
    schema = f"run_queue_pre_pool_{uuid4().hex}"
    admin = await asyncpg.connect(test_infrastructure.timescaledb_url)
    await admin.execute(f"CREATE SCHEMA {schema}")
    pool = await asyncpg.create_pool(
        test_infrastructure.timescaledb_url, server_settings={"search_path": schema}
    )
    assert pool is not None
    try:
        async with pool.acquire() as conn:
            await conn.execute(_PRE_POOL_SCHEMA.read_text())
        yield pool
    finally:
        await pool.close()
        await admin.execute(f"DROP SCHEMA {schema} CASCADE")
        await admin.close()


async def test_upgrading_a_pre_pool_schema_keeps_rows_assigns_default_and_drops_backend(
    pre_pool: asyncpg.Pool,
) -> None:
    async with pre_pool.acquire() as conn:
        # The previous generation's writes, in its own statements' shape.
        await conn.execute(
            """INSERT INTO executor_hosts (host_id,container_id,generation,epoch)
            VALUES ('old','c-old','g0',1)"""
        )
        await conn.execute(
            """INSERT INTO execution_budget (executor_id,container_id,capacity,in_use,heartbeat_at)
            VALUES ('old','c-old',2,1,now())"""
        )
        await conn.execute(
            """INSERT INTO execution_runs (execution_id,state,is_resume,writer_epoch,
                executor_id,lease_token,leased_until,admitted_at)
            VALUES ('exec-held','claimed',FALSE,1,'old',1,now()+interval '1 hour',now())"""
        )

    queue = PostgresExecutionRunQueue(pre_pool)
    await queue.ensure_ready()
    await queue.ensure_ready()

    async with pre_pool.acquire() as conn:
        assert (
            await conn.fetchval("SELECT pool_id FROM execution_budget WHERE executor_id='old'")
            == "default"
        )
        assert await _pool_row(conn, "default") == (0, "docker", None, 10, [], 60)
        assert not await conn.fetchval(
            """SELECT EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name='execution_budget'
            AND column_name='backend')"""
        )
        assert (
            await conn.fetchval(
                """SELECT count(*) FROM pg_constraint
            WHERE conrelid='execution_budget'::regclass AND contype='f'"""
            )
            == 1
        )
    await queue.close(
        ClaimedRun(execution_id="exec-held", executor_id="old", token=1, is_resume=False)
    )
    async with pre_pool.acquire() as conn:
        assert (
            await conn.fetchval("SELECT in_use FROM execution_budget WHERE executor_id='old'") == 0
        )
    # An executor that names no pool joins the seeded one.
    await queue.register(_host("new"), 1)


async def _expire_claims(pool: asyncpg.Pool, executor_id: str, *, expected: int) -> None:
    """Move one executor's leases into the past, keeping their order, without waiting."""
    async with pool.acquire() as conn:
        status = await conn.execute(
            """UPDATE execution_runs SET leased_until=leased_until-interval '1 day'
            WHERE executor_id=$1 AND state='claimed'""",
            executor_id,
        )
    assert status == f"UPDATE {expected}"


async def test_fencing_is_bounded_and_concurrent_fencers_never_share_a_row(
    pools: list[asyncpg.Pool],
) -> None:
    """D5: a reconciler acquires no more than its free slots, so expired rows are shared."""
    dying = PostgresExecutionRunQueue(pools[0])
    first = PostgresExecutionRunQueue(pools[1])
    second = PostgresExecutionRunQueue(pools[2])
    await _online(dying, "dying", capacity=6)
    await _online(first, "rec-1", capacity=1)
    await _online(second, "rec-2", capacity=1)
    for n in range(6):
        await _admit(dying, f"exec-{n}")
        assert await dying.claim("dying") is not None
    await _expire_claims(pools[0], "dying", expected=6)

    a, b = await asyncio.gather(
        first.fence_expired("rec-1", limit=2), second.fence_expired("rec-2", limit=2)
    )
    assert (len(a), len(b)) == (2, 2)
    assert not {r.execution_id for r in a} & {r.execution_id for r in b}
    assert (await first.in_use()).claimed == 2
    assert await first.reconciling("rec-1") == sorted(a, key=lambda r: r.execution_id)


async def test_a_lone_fencer_takes_no_more_than_its_limit(pools: list[asyncpg.Pool]) -> None:
    """The bound is per statement, not a race: an IN (... LIMIT) pick was rescanned per row."""
    dying = PostgresExecutionRunQueue(pools[0])
    lone = PostgresExecutionRunQueue(pools[1])
    await _online(dying, "dying", capacity=6)
    await _online(lone, "rec-1", capacity=1)
    for n in range(6):
        await _admit(dying, f"exec-{n}")
        assert await dying.claim("dying") is not None
    await _expire_claims(pools[0], "dying", expected=6)

    assert len(await lone.fence_expired("rec-1", limit=2)) == 2
    assert len(await lone.reconciling("rec-1")) == 2


async def test_takeover_is_bounded_and_concurrent_adopters_never_share_a_row(
    pools: list[asyncpg.Pool],
) -> None:
    dying = PostgresExecutionRunQueue(pools[0])
    gone = PostgresExecutionRunQueue(pools[1])
    first = PostgresExecutionRunQueue(pools[2])
    second = PostgresExecutionRunQueue(pools[3])
    await _online(dying, "dying", capacity=5)
    await _online(gone, "gone", capacity=1)
    await _online(first, "rec-1", capacity=1)
    await _online(second, "rec-2", capacity=1)
    for n in range(5):
        await _admit(dying, f"exec-{n}")
        assert await dying.claim("dying") is not None
    await _expire_claims(pools[0], "dying", expected=5)
    assert len(await gone.fence_expired("gone", limit=10)) == 5
    assert await first.take_over("rec-1", limit=10) == []  # still registered
    await gone.deregister("gone")

    a, b = await asyncio.gather(
        first.take_over("rec-1", limit=2), second.take_over("rec-2", limit=2)
    )
    assert (len(a), len(b)) == (2, 2)
    assert not {r.execution_id for r in a} & {r.execution_id for r in b}
    assert len(await first.reconciling("rec-1")) == 2
