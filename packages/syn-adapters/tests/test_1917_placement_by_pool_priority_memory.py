"""The Run Queue double places by Pool Priority as Postgres does (#1917, ADR-072 D13).

The real-Postgres acceptance is ``test_1917_placement_by_pool_priority_postgres.py``;
these keep the double, which host-loop tests drive, to the same rule.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_domain.contexts.orchestration.ports import (
    ClaimedRun,
    ExecutorHost,
    ExecutorPool,
    IsolationLevel,
    RunWorkload,
)

pytestmark = pytest.mark.unit

LOCAL = ExecutorPool(pool_id="local", priority=0, provider="docker")
SECOND = ExecutorPool(
    pool_id="second-box",
    priority=1,
    provider="docker",
    overflow_delay=timedelta(seconds=60),
    overflow_budget_usd_per_day=20,
)
E2B = ExecutorPool(
    pool_id="e2b",
    priority=2,
    provider="e2b",
    isolation=IsolationLevel.MICROVM,
    supplies_credentials=False,
    overflow_delay=timedelta(0),
    overflow_budget_usd_per_day=50,
)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 27, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def _join(
    queue: InMemoryExecutionRunQueue,
    host_id: str,
    pool: ExecutorPool,
    capacity: int,
    *,
    epoch: int = 1,
) -> None:
    host = ExecutorHost(
        host_id=host_id,
        container_id=f"c-{host_id}",
        generation="g1",
        epoch=epoch,
        reap_scope=f"scope-{pool.pool_id}",
        pool=pool,
    )
    await queue.register(host, capacity)
    await queue.heartbeat(host_id)


async def _admit(
    queue: InMemoryExecutionRunQueue, *ids: str, workload: RunWorkload = RunWorkload.SCRIPTED
) -> None:
    for execution_id in ids:
        assert await queue.reserve(execution_id, 1, is_resume=False, workload=workload)
        await queue.mark_admitted(execution_id)


def _placed(run: ClaimedRun | None) -> tuple[str, str, bool] | None:
    return None if run is None else (run.execution_id, run.pool_id, run.overflowed)


async def test_a_lower_priority_executor_claims_nothing_while_a_higher_one_has_room() -> None:
    queue = InMemoryExecutionRunQueue(clock=_Clock())
    await _join(queue, "local-1", LOCAL, capacity=2)
    await _join(queue, "e2b-1", E2B, capacity=4)
    assert await queue.claim("local-1") is None
    await _admit(queue, "run-1")

    assert await queue.claim("e2b-1") is None
    assert (await queue.in_use()).admitted == 1


async def test_tiers_fill_in_priority_order_oldest_first_then_queue() -> None:
    clock = _Clock()
    queue = InMemoryExecutionRunQueue(clock=clock)
    await _join(queue, "local-1", LOCAL, capacity=1)
    await _join(queue, "second-1", SECOND, capacity=1)
    await _join(queue, "e2b-1", E2B, capacity=1)
    await _admit(queue, "run-1", "run-2", "run-3", "run-4")

    assert _placed(await queue.claim("local-1")) == ("run-1", "local", False)
    # Priority 1 waits out its delay on a just-full priority 0; priority 2's
    # delay is zero, but priority 1 still has room and is claiming.
    assert await queue.claim("second-1") is None
    assert await queue.claim("e2b-1") is None
    clock.now += timedelta(seconds=61)
    for host_id in ("local-1", "second-1", "e2b-1"):
        await queue.heartbeat(host_id)
    assert _placed(await queue.claim("second-1")) == ("run-2", "second-box", True)
    assert _placed(await queue.claim("e2b-1")) == ("run-3", "e2b", True)
    # Every tier full: the rest stays queued.
    assert await queue.claim("e2b-1") is None
    assert (await queue.in_use()).admitted == 1


async def test_a_no_credentials_executor_never_claims_an_agent_run() -> None:
    queue = InMemoryExecutionRunQueue(clock=_Clock())
    await _join(queue, "e2b-1", E2B, capacity=4)
    await _admit(queue, "agent-1", workload=RunWorkload.AGENT)
    await _admit(queue, "scripted-1")

    assert _placed(await queue.claim("e2b-1")) == ("scripted-1", "e2b", False)
    assert await queue.claim("e2b-1") is None


async def test_a_no_credentials_higher_pool_never_holds_an_agent_run_back() -> None:
    queue = InMemoryExecutionRunQueue(clock=_Clock())
    await _join(queue, "e2b-1", E2B.model_copy(update={"priority": 0}), capacity=4)
    await _join(queue, "second-1", SECOND, capacity=1)
    assert await queue.claim("e2b-1") is None
    await _admit(queue, "agent-1", workload=RunWorkload.AGENT)

    assert _placed(await queue.claim("second-1")) == ("agent-1", "second-box", False)


async def test_a_higher_executor_that_cannot_read_the_runs_epoch_never_holds_it_back() -> None:
    queue = InMemoryExecutionRunQueue(clock=_Clock())
    await _join(queue, "local-1", LOCAL, capacity=2, epoch=1)
    await _join(queue, "second-1", SECOND, capacity=1, epoch=2)
    assert await queue.claim("local-1") is None
    assert await queue.reserve("run-1", 2, is_resume=False, workload=RunWorkload.AGENT)
    await queue.mark_admitted("run-1")

    assert _placed(await queue.claim("second-1")) == ("run-1", "second-box", False)


async def test_without_an_overflow_budget_a_lower_pool_never_overflows_even_when_the_higher_is_full() -> (
    None
):
    clock = _Clock()
    queue = InMemoryExecutionRunQueue(clock=clock)
    await _join(queue, "local-1", LOCAL, capacity=1)
    unbudgeted = E2B.model_copy(update={"overflow_budget_usd_per_day": None})
    await _join(queue, "e2b-1", unbudgeted, capacity=4)
    await _admit(queue, "run-1", "run-2")
    assert _placed(await queue.claim("local-1")) == ("run-1", "local", False)
    clock.now += timedelta(hours=1)
    for host_id in ("local-1", "e2b-1"):
        await queue.heartbeat(host_id)

    assert await queue.claim("e2b-1") is None
    assert (await queue.in_use()).admitted == 1
