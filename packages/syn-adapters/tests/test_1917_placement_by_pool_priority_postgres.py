"""Real-Postgres acceptance for placement by Pool Priority, then queue (#1917, ADR-072 D13).

An executor claims only when no live, non-draining executor in a
higher-priority Executor Pool that could take the run is claiming with room,
or has been full for less than the claiming pool's Overflow Delay. A
NoCredentials pool (E2B) claims only scripted runs and never holds an agent
run back. Ages are set by direct UPDATE, as the #1310 staleness tests do.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

# The #1310 fixture: four asyncpg connection pools on one fresh schema.
from test_execution_run_queue_postgres import pools  # noqa: F401

from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    ExecutorPool,
    IsolationLevel,
    RunWorkload,
)

if TYPE_CHECKING:
    import asyncpg

pytestmark = pytest.mark.integration

_NOW = timedelta(0)
LOCAL = ExecutorPool(pool_id="local", priority=0, provider="docker")
SECOND = ExecutorPool(pool_id="second-box", priority=1, provider="docker", overflow_delay=_NOW)
E2B = ExecutorPool(
    pool_id="e2b",
    priority=2,
    provider="e2b",
    isolation=IsolationLevel.MICROVM,
    supplies_credentials=False,
    overflow_delay=_NOW,
)


def _executor(host_id: str, pool: ExecutorPool, epoch: int = 1) -> ExecutorHost:
    return ExecutorHost(
        host_id=host_id,
        container_id=f"c-{host_id}",
        generation="g1",
        epoch=epoch,
        reap_scope=f"scope-{pool.pool_id}",
        pool=pool,
    )


async def _join(
    queue: PostgresExecutionRunQueue,
    host_id: str,
    pool: ExecutorPool,
    capacity: int,
    *,
    epoch: int = 1,
) -> None:
    await queue.register(_executor(host_id, pool, epoch), capacity)
    await queue.heartbeat(host_id)


async def _admit(
    queue: PostgresExecutionRunQueue,
    *ids: str,
    workload: RunWorkload = RunWorkload.SCRIPTED,
    writer_epoch: int = 1,
) -> None:
    for execution_id in ids:
        assert await queue.reserve(execution_id, writer_epoch, is_resume=False, workload=workload)
        await queue.mark_admitted(execution_id)


async def _untouched(pool: asyncpg.Pool, *ids: str) -> None:
    """Still queued, never claimed: no token moved and nothing was charged."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT execution_id,state,lease_token FROM execution_runs
            WHERE execution_id=ANY($1::text[]) ORDER BY execution_id""",
            list(ids),
        )
    assert [(r["execution_id"], r["state"], r["lease_token"]) for r in rows] == [
        (execution_id, "admitted", 0) for execution_id in sorted(ids)
    ]


def _placed(run: ClaimedRun | None) -> tuple[str, str, bool] | None:
    return None if run is None else (run.execution_id, run.pool_id, run.overflowed)


async def test_a_lower_priority_executor_claims_nothing_while_a_higher_one_has_room(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=2)
    await _join(queue, "e2b-1", E2B, capacity=4)
    assert await queue.claim("local-1") is None  # a Claim Check with room
    await _admit(queue, "run-1", "run-2")

    claims = await asyncio.gather(*(PostgresExecutionRunQueue(p).claim("e2b-1") for p in pools))

    assert claims == [None] * len(pools)
    await _untouched(pools[0], "run-1", "run-2")


async def test_with_the_higher_executor_full_the_lower_one_claims_the_oldest_admitted_run(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=1)
    await _join(queue, "e2b-1", E2B, capacity=4)
    await _admit(queue, "run-1", "run-2", "run-3")

    assert _placed(await queue.claim("local-1")) == ("run-1", "local", False)
    assert _placed(await queue.claim("e2b-1")) == ("run-2", "e2b", True)

    async with pools[0].acquire() as conn:
        row = await conn.fetchrow(
            """SELECT placed_pool,overflowed,claimed_at IS NOT NULL AS stamped
            FROM execution_runs WHERE execution_id='run-2'"""
        )
    assert row is not None
    assert (row["placed_pool"], row["overflowed"], row["stamped"]) == ("e2b", True, True)


async def test_with_priorities_zero_and_one_full_a_priority_two_executor_claims_the_oldest(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=1)
    await _join(queue, "second-1", SECOND, capacity=1)
    await _join(queue, "e2b-1", E2B, capacity=4)
    await _admit(queue, "run-1", "run-2", "run-3", "run-4")

    assert _placed(await queue.claim("local-1")) == ("run-1", "local", False)
    assert _placed(await queue.claim("second-1")) == ("run-2", "second-box", True)
    assert _placed(await queue.claim("e2b-1")) == ("run-3", "e2b", True)


async def test_with_priority_one_free_a_priority_two_executor_claims_nothing(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=1)
    await _join(queue, "second-1", SECOND, capacity=2)
    await _join(queue, "e2b-1", E2B, capacity=4)
    await _admit(queue, "run-1", "run-2")
    assert _placed(await queue.claim("local-1")) == ("run-1", "local", False)
    assert _placed(await queue.claim("second-1")) == ("run-2", "second-box", True)
    await _admit(queue, "run-3")

    assert await queue.claim("e2b-1") is None
    await _untouched(pools[0], "run-3")


async def test_overflow_waits_until_the_higher_executor_has_been_full_for_the_delay(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    patient = SECOND.model_copy(update={"overflow_delay": timedelta(seconds=60)})
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=1)
    await _join(queue, "second-1", patient, capacity=1)
    await _admit(queue, "run-1", "run-2")
    assert _placed(await queue.claim("local-1")) == ("run-1", "local", False)

    assert await queue.claim("second-1") is None
    async with pools[0].acquire() as conn:
        await conn.execute(
            """UPDATE execution_budget SET full_since=clock_timestamp()-interval '61 seconds'
            WHERE executor_id='local-1'"""
        )
    assert _placed(await queue.claim("second-1")) == ("run-2", "second-box", True)


@pytest.mark.parametrize(
    ("unavailable", "spilled_past_it"),
    [
        ("UPDATE execution_budget SET heartbeat_at='-infinity' WHERE executor_id='local-1'", False),
        ("UPDATE executor_hosts SET draining=TRUE WHERE host_id='local-1'", False),
        # Live and with room, but its claim has not run: it holds nothing back.
        (
            "UPDATE execution_budget SET claim_checked_at='-infinity' WHERE executor_id='local-1'",
            True,
        ),
    ],
    ids=["stale", "draining", "not-claiming"],
)
async def test_a_stale_draining_or_not_claiming_higher_executor_is_overflowed_past_at_once(
    pools: list[asyncpg.Pool],  # noqa: F811
    unavailable: str,
    spilled_past_it: bool,
) -> None:
    patient = SECOND.model_copy(update={"overflow_delay": timedelta(seconds=60)})
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=2)
    await _join(queue, "second-1", patient, capacity=1)
    assert await queue.claim("local-1") is None
    await _admit(queue, "run-1")
    async with pools[0].acquire() as conn:
        await conn.execute(unavailable)

    assert _placed(await queue.claim("second-1")) == ("run-1", "second-box", spilled_past_it)


async def test_a_no_credentials_executor_never_claims_an_agent_run(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "e2b-1", E2B, capacity=4)
    # A second member declaring the same pool joins: the declaration round-trips.
    await _join(queue, "e2b-2", E2B, capacity=4)
    await _admit(queue, "agent-1", workload=RunWorkload.AGENT)
    await _admit(queue, "scripted-1")

    assert _placed(await queue.claim("e2b-1")) == ("scripted-1", "e2b", False)
    assert await queue.claim("e2b-1") is None
    assert await queue.claim("e2b-2") is None
    await _untouched(pools[0], "agent-1")


async def test_a_no_credentials_higher_pool_never_holds_an_agent_run_back(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    e2b_first = E2B.model_copy(update={"priority": 0})
    patient = SECOND.model_copy(update={"overflow_delay": timedelta(seconds=60)})
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "e2b-1", e2b_first, capacity=4)
    await _join(queue, "second-1", patient, capacity=1)
    assert await queue.claim("e2b-1") is None
    await _admit(queue, "agent-1", workload=RunWorkload.AGENT)

    assert _placed(await queue.claim("second-1")) == ("agent-1", "second-box", False)


async def test_a_higher_executor_that_cannot_read_the_runs_epoch_never_holds_it_back(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    patient = SECOND.model_copy(update={"overflow_delay": timedelta(seconds=60)})
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=2, epoch=1)
    await _join(queue, "second-1", patient, capacity=1, epoch=2)
    assert await queue.claim("local-1") is None
    await _admit(queue, "run-1", writer_epoch=2)

    assert _placed(await queue.claim("second-1")) == ("run-1", "second-box", False)


async def test_equal_priority_pools_both_claim_without_delay(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    beside = LOCAL.model_copy(update={"pool_id": "local-b", "overflow_delay": timedelta(hours=1)})
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=2)
    await _join(queue, "local-b-1", beside, capacity=2)
    assert await queue.claim("local-1") is None
    await _admit(queue, "run-1")

    assert _placed(await queue.claim("local-b-1")) == ("run-1", "local-b", False)


async def _signals(pool: asyncpg.Pool, executor_id: str) -> tuple[float, object]:
    """The Claim Check as epoch seconds (``-inf`` if never stamped) and ``full_since``."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT extract(epoch FROM claim_checked_at)::float8 AS claim_checked_at,
            full_since FROM execution_budget WHERE executor_id=$1""",
            executor_id,
        )
    assert row is not None
    return row["claim_checked_at"], row["full_since"]


async def test_claim_stamps_its_claim_check_with_and_without_a_run_and_when_full(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=1)
    stamps = [(await _signals(pools[0], "local-1"))[0]]

    assert await queue.claim("local-1") is None
    stamps.append((await _signals(pools[0], "local-1"))[0])
    await _admit(queue, "run-1")
    assert await queue.claim("local-1") is not None
    stamps.append((await _signals(pools[0], "local-1"))[0])
    assert await queue.claim("local-1") is None  # full
    stamps.append((await _signals(pools[0], "local-1"))[0])

    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)


async def test_a_draining_executors_claim_leaves_its_claim_check_unstamped(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=1)
    async with pools[0].acquire() as conn:
        await conn.execute("UPDATE executor_hosts SET draining=TRUE WHERE host_id='local-1'")

    assert await queue.claim("local-1") is None
    checked, _ = await _signals(pools[0], "local-1")
    assert checked == float("-inf")


async def test_full_since_tracks_claim_release_and_an_older_images_raw_writes(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=1)
    await _admit(queue, "run-1")
    assert (await _signals(pools[0], "local-1"))[1] is None

    run = await queue.claim("local-1")
    assert run is not None
    became_full = (await _signals(pools[0], "local-1"))[1]
    assert became_full is not None
    assert await queue.claim("local-1") is None
    assert (await _signals(pools[0], "local-1"))[1] == became_full  # kept while full

    await queue.close(run)
    assert (await _signals(pools[0], "local-1"))[1] is None

    # An image from before the column writes in_use and knows nothing of it.
    async with pools[0].acquire() as conn:
        await conn.execute(
            "UPDATE execution_budget SET in_use=in_use+1 WHERE executor_id='local-1'"
        )
        assert (await _signals(pools[0], "local-1"))[1] is not None
        await conn.execute("UPDATE execution_budget SET capacity=2 WHERE executor_id='local-1'")
    assert (await _signals(pools[0], "local-1"))[1] is None


async def test_concurrent_claims_across_priorities_never_exceed_capacity_and_fill_every_row(
    pools: list[asyncpg.Pool],  # noqa: F811
) -> None:
    capacities = {"local-1": 2, "second-1": 3, "second-2": 3}
    queue = PostgresExecutionRunQueue(pools[0])
    await _join(queue, "local-1", LOCAL, capacity=capacities["local-1"])
    await _join(queue, "second-1", SECOND, capacity=capacities["second-1"])
    await _join(queue, "second-2", SECOND, capacity=capacities["second-2"])
    await _admit(queue, *(f"run-{i:02}" for i in range(20)))
    queues = [PostgresExecutionRunQueue(p) for p in pools]
    hosts = list(capacities) * 14

    claimed: list[ClaimedRun] = []
    while batch := [
        c
        for c in await asyncio.gather(*(queues[i % 4].claim(h) for i, h in enumerate(hosts)))
        if c is not None
    ]:
        claimed.extend(batch)
        async with pools[0].acquire() as conn:
            rows = await conn.fetch("SELECT executor_id,in_use,capacity FROM execution_budget")
        assert all(r["in_use"] <= r["capacity"] for r in rows)

    assert len({c.execution_id for c in claimed}) == len(claimed)
    assert len(claimed) == sum(capacities.values())
