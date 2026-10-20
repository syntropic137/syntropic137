"""ExecutionHost on real Postgres and the real event store (#1310 1.5, ADR-072 V4 + V12 core).

Reuses the wiring of ``test_1310_a_claimed_three_phase_run_succeeds_on_real_stores``:
a real Run Queue, fresh gRPC clients per processor, a fake agent and the memory
workspace backend. Nothing else is a double except the dead-host reaper, which
needs Docker (V7/V7b are E2E and not proven here).

* V4: two ExecutionHosts, each with a budget row of 1, three admitted runs.
  No host ever holds more than its one claim; all three complete; each stream
  has exactly one start and one terminal event.
* V12 core, with expiry simulated by a 1 s lease instead of SIGSTOP:
  - an unexpired claim is neither claimable nor fenceable by another host;
  - after expiry a live host fences it, reaps BEFORE it interrupts, interrupts
    it through the aggregate and frees the dead host's slot, without running it;
  - the stale owner is refused everywhere: ``renew`` and ``close`` raise
    ``RunLeaseLost`` and its own interrupt append raises
    ``ConcurrencyConflictError``; the stream holds one ``WorkflowExecutionStarted``.

Run: ``uv run pytest -m integration apps/syn-api/tests/integration/test_1310_execution_host_claims_fences_and_reconciles_on_real_stores.py``
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from event_sourcing import ConcurrencyConflictError

from syn_adapters.execution_host import AggregateRunInterrupter, ExecutionHost, HostTiming
from syn_adapters.execution_runs import PostgresExecutionRunQueue
from syn_adapters.storage.repositories import EventStoreExecutionEventStream
from syn_domain.contexts.orchestration import ORCHESTRATION_EVENT_EPOCH
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    InterruptExecutionCommand,
)
from syn_domain.contexts.orchestration.ports import ExecutorHost, FencedRun, RunLeaseLost
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler

from .test_1310_a_claimed_three_phase_run_succeeds_on_real_stores import (  # noqa: F401  # fixtures
    _Infra,
    _start,
    infra,
    pool,
)

if TYPE_CHECKING:
    import asyncpg

    from syn_domain.contexts.orchestration.ports import ClaimedRun

pytestmark = pytest.mark.integration

_BUDGET_SECONDS = 60
_TERMINAL = {"WorkflowCompleted", "WorkflowFailed", "WorkflowInterrupted", "WorkflowCancelled"}
_FAST = HostTiming(loop_interval=timedelta(milliseconds=50))


def _host(host_id: str) -> ExecutorHost:
    return ExecutorHost(
        host_id=f"{host_id}-{uuid4().hex[:6]}",
        container_id=f"c-{host_id}",
        generation="g1",
        epoch=ORCHESTRATION_EVENT_EPOCH,
    )


class _Reaper:
    """Records each reap and what the stream held at that moment (V12 ordering)."""

    def __init__(self, world: _Infra) -> None:
        self._infra = world
        self.reaps: list[tuple[str, str, list[str]]] = []

    async def reap(self, run: FencedRun) -> bool:
        seen = await self._infra.event_types(run.execution_id)
        self.reaps.append((run.executor_id, run.execution_id, seen))
        return True


class _MustNotRun:
    def __init__(self) -> None:
        self.claimed: list[str] = []

    async def run_claimed(self, claimed: ClaimedRun) -> object:
        self.claimed.append(claimed.execution_id)
        raise AssertionError(f"{claimed.execution_id} was claimed to run again")


async def _execution_host(
    infra: _Infra,  # noqa: F811  # a plain argument, not the fixture
    host: ExecutorHost,
    drainer: object,
    reaper: _Reaper,
) -> ExecutionHost:
    return ExecutionHost(
        infra.queue,
        host,
        capacity=1,
        drainer=drainer,  # type: ignore[arg-type]
        reaper=reaper,
        interrupter=AggregateRunInterrupter(await infra.executions()),
        streams=EventStoreExecutionEventStream(await infra.client()),
        timing=_FAST,
    )


async def _claimed_per_host(runs: asyncpg.Pool) -> dict[str, int]:
    async with runs.acquire() as conn:
        rows = await conn.fetch(
            "SELECT executor_id,count(*) AS n FROM execution_runs "
            "WHERE state='claimed' GROUP BY executor_id"
        )
    return {row["executor_id"]: row["n"] for row in rows}


async def test_v4_two_hosts_with_budget_one_each_never_exceed_it_and_finish_every_run(
    infra: _Infra,  # noqa: F811  # the fixture imported above
    pool: asyncpg.Pool,  # noqa: F811
) -> None:
    ids = [f"exec-{uuid4().hex[:12]}" for _ in range(3)]
    admitting, _ = await infra.processor(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE), queued=True
    )
    for execution_id in ids:
        assert await _start(admitting, execution_id) == "admitted"

    hosts: list[ExecutionHost] = []
    for name in ("a", "b"):
        processor, _ = await infra.processor(
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE), queued=True
        )
        hosts.append(await _execution_host(infra, _host(name), processor, _Reaper(infra)))
    loops = [asyncio.create_task(h.run_until_drained()) for h in hosts]

    peak: dict[str, int] = {}
    async with asyncio.timeout(_BUDGET_SECONDS):
        while (await infra.queue.in_use()).done < len(ids):
            for host_id, n in (await _claimed_per_host(pool)).items():
                peak[host_id] = max(peak.get(host_id, 0), n)
            await asyncio.sleep(0.01)
    for h in hosts:
        h.drain()
    await asyncio.wait_for(asyncio.gather(*loops), _BUDGET_SECONDS)

    assert peak, "no claim was ever observed"
    assert max(peak.values()) == 1, peak
    counts = await infra.queue.in_use()
    assert (counts.done, counts.claimed, counts.admitted) == (3, 0, 0), counts
    for execution_id in ids:
        types = await infra.event_types(execution_id)
        assert types.count("WorkflowExecutionStarted") == 1, types
        assert [t for t in types if t in _TERMINAL] == ["WorkflowCompleted"], types
        assert types[-1] == "WorkflowCompleted", types
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT sum(in_use) FROM execution_budget") == 0


async def test_v12_an_expired_claim_is_fenced_and_interrupted_once_and_its_stale_owner_refused(
    infra: _Infra,  # noqa: F811  # the fixture imported above
    pool: asyncpg.Pool,  # noqa: F811
) -> None:
    execution_id = f"exec-{uuid4().hex[:12]}"
    admitting, _ = await infra.processor(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE), queued=True
    )
    assert await _start(admitting, execution_id) == "admitted"

    # Executor A claims with a 1 s lease, holds its own copy of the aggregate, then stalls.
    dead, live = _host("a"), _host("b")
    stalled_queue = PostgresExecutionRunQueue(pool, lease_ttl=timedelta(seconds=1))
    await stalled_queue.register(dead, capacity=1)
    await stalled_queue.heartbeat(dead.host_id)
    claimed = await stalled_queue.claim(dead.host_id)
    assert claimed is not None
    assert claimed.execution_id == execution_id
    stale = await (await infra.executions()).get_by_id(execution_id)
    assert stale is not None

    # Before expiry: B can neither claim it nor fence it.
    await infra.queue.register(live, capacity=1)
    await infra.queue.heartbeat(live.host_id)
    assert await infra.queue.claim(live.host_id) is None
    assert await infra.queue.fence_expired(live.host_id, limit=10) == []

    await asyncio.sleep(1.5)

    # After expiry: B's host loop reconciles it, and runs nothing.
    reaper, drainer = _Reaper(infra), _MustNotRun()
    host_b = await _execution_host(infra, live, drainer, reaper)
    loop = asyncio.create_task(host_b.run_until_drained())
    async with asyncio.timeout(_BUDGET_SECONDS):
        while (await infra.queue.in_use()).interrupted < 1:
            await asyncio.sleep(0.02)
    host_b.drain()
    await asyncio.wait_for(loop, _BUDGET_SECONDS)

    assert drainer.claimed == []
    assert len(reaper.reaps) == 1
    reaped_host, reaped_id, seen_at_reap = reaper.reaps[0]
    assert (reaped_host, reaped_id) == (dead.host_id, execution_id)
    assert "WorkflowInterrupted" not in seen_at_reap  # container gone before the interrupt
    types = await infra.event_types(execution_id)
    assert types.count("WorkflowExecutionStarted") == 1, types
    assert types[-1] == "WorkflowInterrupted", types
    async with pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT in_use FROM execution_budget WHERE executor_id=$1", dead.host_id
            )
            == 0
        )

    # A wakes up: every write it attempts is refused.
    with pytest.raises(RunLeaseLost):
        await stalled_queue.renew(claimed)
    with pytest.raises(RunLeaseLost):
        await stalled_queue.close(claimed)
    stale.interrupt_execution(
        InterruptExecutionCommand(execution_id=execution_id, phase_id="", reason="A's 0.2 path")
    )
    with pytest.raises(ConcurrencyConflictError):
        await (await infra.executions()).save(stale)
    after = await infra.event_types(execution_id)
    assert after == types
    assert after.count("WorkflowInterrupted") == 1
