"""The in-memory Run Queue double keeps the Postgres guards and refuses production."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_adapters.in_memory import InMemoryAdapterError
from syn_domain.contexts.orchestration.ports import (
    ExecutorHost,
    ExecutorPool,
    PoolDefinitionConflict,
    RunLeaseLost,
)

pytestmark = pytest.mark.unit


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 8, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _host(host_id: str) -> ExecutorHost:
    return ExecutorHost(host_id=host_id, container_id=f"c-{host_id}", generation="g1", epoch=1)


async def _queue_with(clock: _Clock, capacity: int, *ids: str) -> InMemoryExecutionRunQueue:
    queue = InMemoryExecutionRunQueue(clock=clock)
    await queue.register(_host("h1"), capacity)
    await queue.heartbeat("h1")
    for execution_id in ids:
        assert await queue.reserve(execution_id, 1, is_resume=False)
        await queue.mark_admitted(execution_id)
    return queue


def test_refuses_to_construct_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_shared.settings import get_settings

    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    get_settings.cache_clear()
    try:
        with pytest.raises(InMemoryAdapterError):
            InMemoryExecutionRunQueue()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


async def test_claims_stop_at_capacity_and_release_frees_one_slot() -> None:
    queue = await _queue_with(_Clock(), 2, "a", "b", "c")
    first, second = await queue.claim("h1"), await queue.claim("h1")
    assert first is not None and second is not None
    assert await queue.claim("h1") is None
    await queue.close(first)
    third = await queue.claim("h1")
    assert third is not None
    assert third.execution_id == "c"


async def test_stale_token_is_refused_after_defer_and_reclaim() -> None:
    queue = await _queue_with(_Clock(), 1, "a")
    first = await queue.claim("h1")
    assert first is not None
    await queue.defer(first, timedelta(0), "not readable")
    second = await queue.claim("h1")
    assert second is not None
    with pytest.raises(RunLeaseLost):
        await queue.renew(first)
    with pytest.raises(RunLeaseLost):
        await queue.close(first)
    await queue.renew(second)


async def test_fence_leaves_a_live_lease_alone() -> None:
    clock = _Clock()
    queue = await _queue_with(clock, 1, "a")
    await queue.register(_host("h2"), 1)
    held = await queue.claim("h1")
    assert held is not None
    clock.now += timedelta(seconds=89)
    assert await queue.fence_expired("h2", limit=10) == []
    await queue.renew(held)
    await queue.close(held)


async def test_expired_lease_is_fenced_never_reclaimed() -> None:
    clock = _Clock()
    queue = await _queue_with(clock, 1, "a")
    await queue.register(_host("h2"), 1)
    held = await queue.claim("h1")
    assert held is not None
    clock.now += timedelta(seconds=91)
    await queue.heartbeat("h2")
    assert await queue.claim("h2") is None
    fenced = await queue.fence_expired("h2", limit=10)
    assert [(f.execution_id, f.executor_id) for f in fenced] == [("a", "h1")]
    await queue.mark_reaped(fenced[0])
    await queue.close_interrupted(fenced[0])
    counts = await queue.in_use()
    assert (counts.interrupted, counts.claimed) == (1, 0)


async def test_reconciling_adopts_only_from_a_reconciler_that_left_and_a_restart_leaves() -> None:
    """Mirrors the Postgres takeover and restart predicates (ADR-072 D5)."""
    clock = _Clock()
    queue = await _queue_with(clock, 1, "a")
    for host in ("rec-1", "rec-2"):
        await queue.register(_host(host), 1)
        await queue.heartbeat(host)
    assert await queue.others_live("rec-2")
    assert await queue.claim("h1") is not None
    clock.now += timedelta(minutes=5)
    (fenced,) = await queue.fence_expired("rec-1", limit=10)
    assert await queue.take_over("rec-2", limit=10) == []
    # rec-1 restarts in its container: the new process retires it.
    await queue.register(
        ExecutorHost(host_id="rec-1b", container_id="c-rec-1", generation="g1", epoch=1), 1
    )
    assert await queue.reconciling("rec-2") == []  # reading adopts nothing
    (adopted,) = await queue.take_over("rec-2", limit=10)
    assert (adopted.reconciler, adopted.token) == ("rec-2", fenced.token + 1)
    with pytest.raises(RunLeaseLost):
        await queue.mark_reaped(fenced)
    await queue.mark_reaped(adopted)
    (again,) = await queue.reconciling("rec-2")
    assert again.reaped
    await queue.close_interrupted(again)
    assert await queue.reconciling("rec-2") == []


async def test_a_restart_moves_the_machine_budget_one_release_at_a_time() -> None:
    """Mirrors the Postgres D3 restart rule: summed capacity never changes."""
    clock = _Clock()
    queue = await _queue_with(clock, 1, "held", "waiting")
    held = await queue.claim("h1")
    assert held is not None
    successor = ExecutorHost(host_id="h1.new", container_id="c-h1", generation="g1", epoch=1)
    await queue.register(successor, 1)
    await queue.heartbeat("h1.new")
    assert await queue.claim("h1.new") is None

    clock.now += timedelta(minutes=5)
    await queue.heartbeat("h1.new")
    (fenced,) = await queue.fence_expired("h1.new", limit=10)
    await queue.mark_reaped(fenced)
    await queue.close_interrupted(fenced)
    with pytest.raises(RunLeaseLost):
        await queue.close(held)
    claimed = await queue.claim("h1.new")
    assert claimed is not None and claimed.execution_id == "waiting"
    assert await queue.claim("h1.new") is None


_P1 = ExecutorPool(pool_id="p1", priority=1, provider="docker")


def _in_pool(host_id: str, pool: ExecutorPool, container_id: str | None = None) -> ExecutorHost:
    return ExecutorHost(
        host_id=host_id,
        container_id=container_id or f"c-{host_id}",
        generation="g1",
        epoch=1,
        pool=pool,
    )


async def test_a_differing_declaration_is_refused_while_a_member_is_live_and_writes_nothing() -> (
    None
):
    """Mirrors the Postgres D13 rule, including a member that has not yet beaten."""
    clock = _Clock()
    queue = await _queue_with(clock, 2, "a")
    await queue.register(_in_pool("m", _P1), 1)
    with pytest.raises(PoolDefinitionConflict):
        # In h1's container: a committed registration would have retired h1.
        await queue.register(_in_pool("n", _P1.model_copy(update={"priority": 4}), "c-h1"), 1)
    with pytest.raises(LookupError):
        await queue.heartbeat("n")
    await queue.heartbeat("h1")
    assert await queue.claim("h1") is not None

    # Once m is no longer live the pool may be redefined, and that is what binds next.
    clock.now += timedelta(minutes=5)
    await queue.register(_in_pool("n", _P1.model_copy(update={"priority": 4}), "c-h1"), 1)
    await queue.heartbeat("n")
    with pytest.raises(PoolDefinitionConflict):
        await queue.register(_in_pool("o", _P1), 1)


async def test_a_sole_member_restarting_in_its_container_may_redefine_its_pool() -> None:
    queue = InMemoryExecutionRunQueue(clock=_Clock())
    await queue.register(_in_pool("a.1", _P1, "box"), 1)
    await queue.heartbeat("a.1")
    await queue.register(_in_pool("a.2", _P1.model_copy(update={"region": "eu-west"}), "box"), 1)
    await queue.heartbeat("a.2")
