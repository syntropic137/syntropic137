"""Reconciliation resumes from the durable row (#1310 1.5, ADR-072 D5; verify B2, B3).

Real Postgres Run Queue and the real event store, wired as in
``test_1310_a_claimed_three_phase_run_succeeds_on_real_stores``. Only the reaper
is a double (Docker-backed reaping is ``test_1310_v7_dead_host_reap_on_real_docker``).

* A failure of ``mark_reaped`` or ``close_interrupted``, either before its
  commit or as a lost acknowledgment after it, is resumed on the next turn:
  one ``WorkflowInterrupted``, slot released once.
* A reconciler that dies after the interrupt append and before closing the row
  is not taken over while still registered; once it leaves, a successor closes
  the row without reaping again or appending a second terminal event.

Run: ``uv run pytest -m integration apps/syn-api/tests/integration/test_1310_reconciliation_resumes_from_the_row_on_real_stores.py``
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.execution_host import AggregateRunInterrupter
from syn_adapters.execution_host.reconciler import Reconciler
from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_domain.contexts.orchestration import ORCHESTRATION_EVENT_EPOCH
from syn_domain.contexts.orchestration.ports import ExecutorHost, FencedRun
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler

from .test_1310_a_claimed_three_phase_run_succeeds_on_real_stores import (  # noqa: F401  # fixtures
    _Infra,
    _start,
    infra,
    pool,
)

if TYPE_CHECKING:
    import asyncpg

pytestmark = pytest.mark.integration


def _host(name: str) -> ExecutorHost:
    return ExecutorHost(
        host_id=f"{name}-{uuid4().hex[:6]}",
        container_id=f"c-{name}-{uuid4().hex[:6]}",
        generation="g1",
        epoch=ORCHESTRATION_EVENT_EPOCH,
    )


class _Reaper:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def reap(self, run: FencedRun) -> bool:
        self.calls.append(run.execution_id)
        return True


class _FailsOnce:
    """The real queue, except ``write`` fails once: ``before`` its commit, or
    ``after`` it (a lost acknowledgment)."""

    def __init__(self, queue: PostgresExecutionRunQueue, write: str, when: str) -> None:
        self._queue, self._write, self._when, self.lost = queue, write, when, False

    def __getattr__(self, name: str) -> object:
        real = getattr(self._queue, name)
        if name != self._write or self.lost:
            return real

        async def fail_once(run: FencedRun) -> None:
            if self._when == "after":
                await real(run)
            self.lost = True
            raise ConnectionError(f"{name} failed {self._when} its commit")

        return fail_once


async def _expired_claim(world: _Infra, runs: asyncpg.Pool) -> tuple[str, ExecutorHost]:
    execution_id = f"exec-{uuid4().hex[:12]}"
    admitting, _ = await world.processor(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE), queued=True
    )
    assert await _start(admitting, execution_id) == "admitted"
    dead = _host("dead")
    short = PostgresExecutionRunQueue(runs, lease_ttl=timedelta(seconds=1))
    await short.register(dead, capacity=1)
    await short.heartbeat(dead.host_id)
    claimed = await short.claim(dead.host_id)
    assert claimed is not None
    assert claimed.execution_id == execution_id
    await asyncio.sleep(1.5)
    return execution_id, dead


async def _online(world: _Infra, host: ExecutorHost) -> None:
    await world.queue.register(host, capacity=1)
    await world.queue.heartbeat(host.host_id)


async def _assert_closed_once(
    world: _Infra,
    runs: asyncpg.Pool,
    execution_id: str,
    dead: ExecutorHost,
) -> None:
    counts = await world.queue.in_use()
    assert (counts.interrupted, counts.fencing, counts.reaped, counts.claimed) == (1, 0, 0, 0)
    types = await world.event_types(execution_id)
    assert types.count("WorkflowExecutionStarted") == 1, types
    assert types.count("WorkflowInterrupted") == 1, types
    assert types[-1] == "WorkflowInterrupted", types
    async with runs.acquire() as conn:
        in_use = await conn.fetchval(
            "SELECT in_use FROM execution_budget WHERE executor_id=$1", dead.host_id
        )
    assert in_use == 0


async def _reconcile_turn(reconciler: Reconciler) -> None:
    """One acquiring turn, then wait for its attempts: a turn no longer awaits them (#1944)."""
    await reconciler.turn(acquire=True)
    async with asyncio.timeout(60):
        while not reconciler.idle:
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("write", ["mark_reaped", "close_interrupted"])
async def test_a_failed_write_is_resumed_from_the_row(
    infra: _Infra,  # noqa: F811
    pool: asyncpg.Pool,  # noqa: F811
    write: str,
    when: str,
) -> None:
    execution_id, dead = await _expired_claim(infra, pool)
    me = _host("rec")
    await _online(infra, me)
    flaky = _FailsOnce(infra.queue, write, when)
    reaper = _Reaper()
    reconciler = Reconciler(
        flaky,  # type: ignore[arg-type]  # the real queue behind a lost-ack proxy
        me.host_id,
        reaper,
        AggregateRunInterrupter(await infra.executions()),
    )
    await _reconcile_turn(reconciler)
    assert flaky.lost
    await _reconcile_turn(reconciler)
    await _reconcile_turn(reconciler)
    # Only a mark_reaped that never committed leaves the row fencing, so the
    # (idempotent) reap runs again; every other case resumes past it.
    reaps = 2 if (write, when) == ("mark_reaped", "before") else 1
    assert reaper.calls == [execution_id] * reaps
    await _assert_closed_once(infra, pool, execution_id, dead)


async def test_a_dead_reconcilers_row_is_finished_by_its_successor_only_after_it_leaves(
    infra: _Infra,  # noqa: F811
    pool: asyncpg.Pool,  # noqa: F811
) -> None:
    execution_id, dead = await _expired_claim(infra, pool)
    first, successor = _host("rec-1"), _host("rec-2")
    await _online(infra, first)
    await _online(infra, successor)

    # rec-1 fences, reaps and interrupts, then dies before closing the row.
    (fenced,) = await infra.queue.fence_expired(first.host_id, limit=10)
    await infra.queue.mark_reaped(fenced)
    await AggregateRunInterrupter(await infra.executions()).interrupt(fenced)

    reaper = _Reaper()
    rec2 = Reconciler(
        infra.queue, successor.host_id, reaper, AggregateRunInterrupter(await infra.executions())
    )
    await _reconcile_turn(rec2)
    assert (await infra.queue.in_use()).reaped == 1  # rec-1 is still registered

    await infra.queue.deregister(first.host_id)
    await _reconcile_turn(rec2)
    assert reaper.calls == []  # the row said reaped
    await _assert_closed_once(infra, pool, execution_id, dead)
