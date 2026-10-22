"""Reap Scope and reap-before-close on real Postgres (placement plan PR 2, ADR-072 D3, D5, D13).

A reconciler on another Docker engine sees none of a run's containers, so its
empty reap would read as done and free a slot whose workspace may still run.
These tests pin the two guards: fencing and takeover stay inside the claimer's
Reap Scope, and the owner closes a run only once its reaper shows it released.
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import asyncpg
import pytest

from syn_adapters.execution_host import ExecutionHost, HostTiming
from syn_adapters.execution_host.reconciler import Reconciler
from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    IsolationLevel,
    StreamPresence,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from syn_tests.fixtures.infrastructure import TestInfrastructure

    from syn_domain.contexts.orchestration.ports import FencedRun

pytestmark = pytest.mark.integration

_PRE_SCOPE_SCHEMA = Path(__file__).parent / "fixtures" / "execution_runs" / "schema_pre_scope.sql"


async def _fresh_schema(
    infra: TestInfrastructure, prefix: str, frozen: Path | None
) -> AsyncIterator[asyncpg.Pool]:
    schema = f"{prefix}_{uuid4().hex}"
    admin = await asyncpg.connect(infra.timescaledb_url)
    await admin.execute(f"CREATE SCHEMA {schema}")
    pool = await asyncpg.create_pool(
        infra.timescaledb_url, min_size=1, max_size=10, server_settings={"search_path": schema}
    )
    assert pool is not None
    try:
        if frozen is None:
            await PostgresExecutionRunQueue(pool).ensure_ready()
        else:
            async with pool.acquire() as conn:
                await conn.execute(frozen.read_text())
        yield pool
    finally:
        await pool.close()
        await admin.execute(f"DROP SCHEMA {schema} CASCADE")
        await admin.close()


@pytest.fixture
async def pool(test_infrastructure: TestInfrastructure) -> AsyncIterator[asyncpg.Pool]:
    async for created in _fresh_schema(test_infrastructure, "reap_scope", None):
        yield created


@pytest.fixture
async def pre_scope(test_infrastructure: TestInfrastructure) -> AsyncIterator[asyncpg.Pool]:
    """A schema holding the frozen pre-scope Run Queue tables, not yet upgraded."""
    async for created in _fresh_schema(test_infrastructure, "reap_scope_pre", _PRE_SCOPE_SCHEMA):
        yield created


def _host(host_id: str, scope: str, container_id: str | None = None) -> ExecutorHost:
    return ExecutorHost(
        host_id=host_id,
        container_id=container_id or f"c-{host_id}",
        generation="g1",
        epoch=1,
        reap_scope=scope,
    )


async def _online(queue: PostgresExecutionRunQueue, host: ExecutorHost, capacity: int = 1) -> None:
    await queue.register(host, capacity)
    await queue.heartbeat(host.host_id)


async def _claimed_and_expired(
    pool: asyncpg.Pool, queue: PostgresExecutionRunQueue, host_id: str, execution_id: str
) -> None:
    assert await queue.reserve(execution_id, 1, is_resume=False)
    await queue.mark_admitted(execution_id)
    claimed = await queue.claim(host_id)
    assert claimed is not None and claimed.execution_id == execution_id
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE execution_runs SET leased_until=now()-interval '1 day' WHERE execution_id=$1",
            execution_id,
        )


async def _row(pool: asyncpg.Pool, execution_id: str) -> tuple[str, int | None]:
    """(run state, the claimer's in_use); no claimer once the run is released."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT r.state, b.in_use FROM execution_runs r
            LEFT JOIN execution_budget b ON b.executor_id=r.executor_id
            WHERE r.execution_id=$1""",
            execution_id,
        )
    assert row is not None, execution_id
    return row["state"], row["in_use"]


async def _in_use(pool: asyncpg.Pool, executor_id: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT in_use FROM execution_budget WHERE executor_id=$1", executor_id
        )


class _Reaper:
    """A backend double: records each reap; answers from ``answers`` then ``complete``."""

    def __init__(self, *, complete: bool = True, answers: list[bool | Exception] | None = None):
        self.complete = complete
        self.answers = list(answers or [])
        self.calls: list[tuple[str, str]] = []

    def scope(self) -> str:
        return "unused"

    def provider(self) -> str:
        return "docker"

    def isolation(self) -> IsolationLevel:
        return IsolationLevel.CONTAINER

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        self.calls.append((executor_id, execution_id))
        if self.answers:
            answer = self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return self.complete


class _Interrupter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def interrupt(self, run: FencedRun) -> None:
        self.calls.append(run.execution_id)


async def _reconcile(queue: PostgresExecutionRunQueue, host_id: str, reaper: _Reaper) -> Reconciler:
    """One full acquiring turn, awaited to its end."""
    reconciler = Reconciler(queue, host_id, reaper, _Interrupter())  # type: ignore[arg-type]
    await reconciler.turn(acquire=True)
    async with asyncio.timeout(10):
        while not reconciler.idle:
            await asyncio.sleep(0.01)
    return reconciler


async def test_an_executor_in_another_reap_scope_never_fences_an_expired_run(
    pool: asyncpg.Pool,
) -> None:
    queue = PostgresExecutionRunQueue(pool)
    await _online(queue, _host("a", "s1"))
    await _online(queue, _host("b", "s2"))
    await _online(queue, _host("c", "s1"))
    await _claimed_and_expired(pool, queue, "a", "exec-1")

    assert await queue.fence_expired("b", limit=10) == []
    assert await _row(pool, "exec-1") == ("claimed", 1)

    (fenced,) = await queue.fence_expired("c", limit=10)
    assert (fenced.execution_id, fenced.executor_id, fenced.reconciler) == ("exec-1", "a", "c")


async def test_takeover_requires_the_same_reap_scope(pool: asyncpg.Pool) -> None:
    queue = PostgresExecutionRunQueue(pool)
    await _online(queue, _host("a", "s1"))
    await _online(queue, _host("rec", "s1"))
    await _online(queue, _host("other", "s2"))
    await _online(queue, _host("same", "s1"))
    await _claimed_and_expired(pool, queue, "a", "exec-1")
    (fenced,) = await queue.fence_expired("rec", limit=10)
    await queue.deregister("rec")

    assert await queue.take_over("other", limit=10) == []
    assert await _row(pool, "exec-1") == ("fencing", 1)

    (adopted,) = await queue.take_over("same", limit=10)
    assert (adopted.reconciler, adopted.token) == ("same", fenced.token + 1)


async def test_a_run_with_no_live_executor_in_its_scope_stays_charged(pool: asyncpg.Pool) -> None:
    queue = PostgresExecutionRunQueue(pool)
    await _online(queue, _host("a", "s1"))
    await _online(queue, _host("b", "s2"), capacity=4)
    await _claimed_and_expired(pool, queue, "a", "exec-1")
    await queue.deregister("a")
    reaper = _Reaper(complete=True)  # an empty listing on b's engine: "nothing left"

    await _reconcile(queue, "b", reaper)

    assert reaper.calls == []
    assert await _row(pool, "exec-1") == ("claimed", 1)
    assert await _in_use(pool, "a") == 1


async def test_a_pre_scope_expired_claim_is_scoped_only_by_a_successor_in_its_own_container(
    pre_scope: asyncpg.Pool,
) -> None:
    async with pre_scope.acquire() as conn:
        # The previous generation's writes, in its own statements' shape: the
        # executor in container c-old died holding exec-old.
        await conn.execute(
            """INSERT INTO execution_budget (executor_id,container_id,capacity,in_use,heartbeat_at)
            VALUES ('old','c-old',2,1,now()-interval '1 hour')"""
        )
        await conn.execute(
            """INSERT INTO execution_runs (execution_id,state,is_resume,writer_epoch,
                executor_id,lease_token,leased_until,admitted_at)
            VALUES ('exec-old','claimed',FALSE,1,'old',1,now()-interval '1 hour',now())"""
        )
    queue = PostgresExecutionRunQueue(pre_scope)
    await queue.ensure_ready()
    await queue.ensure_ready()
    async with pre_scope.acquire() as conn:
        assert (
            await conn.fetchval("SELECT reap_scope FROM execution_budget WHERE executor_id='old'")
            is None
        )
    assert await _row(pre_scope, "exec-old") == ("claimed", 1)

    # D runs in another container on the very engine c-old used: still not proof.
    await _online(queue, _host("d", "engine-1"))
    reaper_d = _Reaper(complete=True)
    await _reconcile(queue, "d", reaper_d)
    assert reaper_d.calls == []
    assert await _row(pre_scope, "exec-old") == ("claimed", 1)

    await _online(queue, _host("e", "engine-1", container_id="c-old"))
    async with pre_scope.acquire() as conn:
        assert (
            await conn.fetchval("SELECT reap_scope FROM execution_budget WHERE executor_id='old'")
            == "engine-1"
        )
    reaper_e = _Reaper(complete=True)
    await _reconcile(queue, "e", reaper_e)
    assert reaper_e.calls == [("old", "exec-old")]
    async with pre_scope.acquire() as conn:
        assert (
            await conn.fetchval("SELECT state FROM execution_runs WHERE execution_id='exec-old'")
            == "interrupted"
        )
    assert await _in_use(pre_scope, "old") == 0


# --- reap-before-close, through the host loop ------------------------------

_TTL = timedelta(milliseconds=600)
_TIMING = HostTiming(
    loop_interval=timedelta(milliseconds=50),
    lease_ttl=_TTL,
    turn_budget=timedelta(milliseconds=100),
)


class _FailedDrain:
    """Drains to a workflow failure: ``_fail_execution`` after a create whose response was lost."""

    def __init__(self) -> None:
        self.done = asyncio.Event()

    async def run_claimed(self, claimed: ClaimedRun) -> object:
        self.done.set()
        return "failed"


class _Streams:
    async def presence(self, execution_id: str) -> StreamPresence:
        return StreamPresence.PRESENT


async def _until(check: Callable[[], Awaitable[bool]], what: str, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while not await check():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.02)


async def _host_loop(
    pool: asyncpg.Pool, reaper: _Reaper
) -> tuple[PostgresExecutionRunQueue, ExecutionHost, _FailedDrain, asyncio.Task[None]]:
    queue = PostgresExecutionRunQueue(pool, lease_ttl=_TTL)
    drain = _FailedDrain()
    host = ExecutionHost(
        queue,
        _host("owner", "s1"),
        capacity=1,
        drainer=drain,
        reaper=reaper,  # type: ignore[arg-type]
        interrupter=_Interrupter(),
        streams=_Streams(),
        timing=_TIMING,
    )
    await host.join()
    assert await queue.reserve("exec-lost", 1, is_resume=False)
    await queue.mark_admitted("exec-lost")
    return queue, host, drain, asyncio.create_task(host.run_until_drained())


async def _stop(host: ExecutionHost, task: asyncio.Task[None]) -> None:
    host.drain()
    try:
        async with asyncio.timeout(10):
            await task
    except TimeoutError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_a_drain_that_returns_normally_over_unreleased_resources_leaves_the_slot_charged(
    pool: asyncpg.Pool,
) -> None:
    reaper = _Reaper(complete=False)
    _queue, host, drain, task = await _host_loop(pool, reaper)
    try:
        await asyncio.wait_for(drain.done.wait(), 10)

        async def owner_settled() -> bool:
            state, _ = await _row(pool, "exec-lost")
            return bool(reaper.calls) or state != "claimed"

        await _until(owner_settled, "the owner's reap or close")
        assert await _row(pool, "exec-lost") == ("claimed", 1)
        assert reaper.calls[0] == ("owner", "exec-lost")

        async def fencing() -> bool:
            return (await _row(pool, "exec-lost"))[0] == "fencing"

        await _until(fencing, "the expired lease to be fenced in the same scope")
        calls = len(reaper.calls)
        await _until(lambda: _gt(reaper.calls, calls), "a retried reconciliation reap")
        assert await _row(pool, "exec-lost") == ("fencing", 1)

        reaper.complete = True

        async def interrupted() -> bool:
            return (await _row(pool, "exec-lost"))[0] == "interrupted"

        await _until(interrupted, "the reap to be shown complete")
        assert await _in_use(pool, "owner") == 0
    finally:
        await _stop(host, task)


async def test_uncertain_delete_keeps_the_slot_until_reap_confirms(pool: asyncpg.Pool) -> None:
    # Two deletes whose outcome is unknown, then listings that still show resources.
    reaper = _Reaper(
        complete=False, answers=[RuntimeError("delete timed out"), RuntimeError("delete timed out")]
    )
    _queue, host, drain, task = await _host_loop(pool, reaper)
    try:
        await asyncio.wait_for(drain.done.wait(), 10)
        await _until(lambda: _gt(reaper.calls, 0), "the owner's reap")
        state, in_use = await _row(pool, "exec-lost")
        assert (state, in_use) == ("claimed", 1)
        await _until(lambda: _gt(reaper.calls, 1), "the reconciler's first reap")
        await _until(lambda: _gt(reaper.calls, 2), "a reconciler reap after the errors")
        assert await _row(pool, "exec-lost") == ("fencing", 1)

        reaper.complete = True

        async def interrupted() -> bool:
            return (await _row(pool, "exec-lost"))[0] == "interrupted"

        await _until(interrupted, "a reap to confirm")
        assert await _in_use(pool, "owner") == 0
    finally:
        await _stop(host, task)


async def _gt(calls: list[tuple[str, str]], n: int) -> bool:
    return len(calls) > n
