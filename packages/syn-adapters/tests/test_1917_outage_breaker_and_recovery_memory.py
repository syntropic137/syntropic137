"""The Run Queue double keeps the Outage Breaker and the C8 fence guard as Postgres does (#1917).

The real-Postgres acceptance is ``test_1917_outage_breaker_and_recovery_postgres.py``;
these keep the double, which host-loop tests drive, to the same rules.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from syn_adapters.execution_host import ExecutionHost
from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_domain.contexts.orchestration.ports import (
    ExecutorHost,
    ExecutorPool,
    IsolationLevel,
    RunWorkload,
)

pytestmark = pytest.mark.unit

E2B_SCOPE = "e2b-key-0123456789abcdef"
LOCAL = ExecutorPool(pool_id="local", priority=0, provider="docker")
E2B = ExecutorPool(
    pool_id="e2b",
    priority=2,
    provider="e2b",
    isolation=IsolationLevel.MICROVM,
    supplies_credentials=False,
    overflow_delay=timedelta(0),
    overflow_budget_usd_per_day=50,
)
_COOLDOWN = timedelta(minutes=5)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 27, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def _join(
    queue: InMemoryExecutionRunQueue,
    host_id: str,
    pool: ExecutorPool,
    scope: str,
    *,
    recovery: frozenset[str] = frozenset(),
) -> None:
    host = ExecutorHost(
        host_id=host_id,
        container_id=f"c-{host_id}",
        generation="g1",
        epoch=1,
        reap_scope=scope,
        pool=pool,
        recovery_scopes=recovery,
    )
    await queue.register(host, 2)
    await queue.heartbeat(host_id)


async def _admit(queue: InMemoryExecutionRunQueue, *ids: str) -> None:
    for execution_id in ids:
        assert await queue.reserve(execution_id, 1, is_resume=False, workload=RunWorkload.SCRIPTED)
        await queue.mark_admitted(execution_id)


async def test_the_breaker_disables_claims_until_the_cooldown_and_a_success_clears() -> None:
    clock = _Clock()
    queue = InMemoryExecutionRunQueue(clock=clock)
    await _join(queue, "e2b-1", E2B, E2B_SCOPE)
    await _admit(queue, "run-1", "run-2", "run-3")
    held = await queue.claim("e2b-1")
    assert held is not None

    tripped = [
        await queue.record_create_failure("e2b-1", threshold=2, cooldown=_COOLDOWN)
        for _ in range(2)
    ]

    assert tripped == [False, True]
    assert await queue.claim("e2b-1") is None
    await queue.close(held)  # a charged run still releases
    clock.now += _COOLDOWN
    await queue.heartbeat("e2b-1")
    probe = await queue.claim("e2b-1")
    assert probe is not None  # half-open: one claim
    assert await queue.claim("e2b-1") is None  # and only one, until its create reports
    assert await queue.record_create_failure("e2b-1", threshold=2, cooldown=_COOLDOWN)
    assert await queue.claim("e2b-1") is None
    await queue.close(probe)
    await queue.record_create_success("e2b-1")
    assert await queue.claim("e2b-1") is not None


async def test_a_disabled_higher_executor_holds_no_lower_pool_back() -> None:
    queue = InMemoryExecutionRunQueue()
    await _join(queue, "local-1", LOCAL, "engine-1")
    await _join(queue, "e2b-1", E2B, E2B_SCOPE)
    assert await queue.claim("local-1") is None  # a Claim Check with room
    await queue.record_create_failure("local-1", threshold=1, cooldown=_COOLDOWN)
    await _admit(queue, "run-1")

    claimed = await queue.claim("e2b-1")

    assert claimed is not None
    assert (claimed.execution_id, claimed.overflowed) == ("run-1", False)


async def test_only_an_executor_holding_the_kit_fences_a_dead_e2b_run() -> None:
    clock = _Clock()
    queue = InMemoryExecutionRunQueue(clock=clock)
    await _join(queue, "e2b-1", E2B, E2B_SCOPE)
    await _admit(queue, "run-1")
    assert await queue.claim("e2b-1") is not None
    clock.now += timedelta(minutes=10)
    await _join(queue, "bare", LOCAL, "engine-1")
    await _join(queue, "kit", LOCAL, "engine-1", recovery=frozenset({E2B_SCOPE}))

    assert await queue.fence_expired("bare", limit=10) == []
    (fenced,) = await queue.fence_expired("kit", limit=10)

    assert (fenced.execution_id, fenced.claimer_scope) == ("run-1", E2B_SCOPE)
    await queue.deregister("kit")
    assert await queue.take_over("bare", limit=10) == []


class _Kit:
    """A Recovery Kit's reaper, as the host reads it."""

    def scope(self) -> str:
        return E2B_SCOPE

    def provider(self) -> str:
        return "e2b"

    def isolation(self) -> IsolationLevel:
        return IsolationLevel.MICROVM

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        return True


@pytest.mark.parametrize(
    ("declared", "held"),
    [(frozenset({E2B_SCOPE}), ()), (frozenset(), (_Kit(),))],
    ids=["declared-without-kit", "kit-undeclared"],
)
def test_a_host_never_declares_a_reach_its_kits_do_not_give_it(
    declared: frozenset[str], held: tuple[_Kit, ...]
) -> None:
    host = ExecutorHost(
        host_id="local-1",
        container_id="c",
        generation="g",
        epoch=1,
        reap_scope="engine-1",
        recovery_scopes=declared,
    )
    with pytest.raises(ValueError, match="recovery scopes"):
        ExecutionHost(
            InMemoryExecutionRunQueue(),
            host,
            capacity=1,
            drainer=MagicMock(),
            reaper=_Kit(),
            interrupter=MagicMock(),
            streams=MagicMock(),
            recovery=held,
        )
