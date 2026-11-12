"""Inventory scheduling is atomic per run across managers (#1534).

Two ``SchedulePendingInventoryHandler`` instances stand for two inventory
managers on one database. Manager A is paused after its open-job check and
before it schedules; evidence then advances the run's watermark and manager B
ticks. Without a per-run guard both pass the check and the store gets two jobs
for one run with different identities (watermark 1 and watermark 2).

The unit half runs on in-memory twins. The integration half runs the same race
on the real Postgres outbox and the real advisory-lock guard, two pooled
connections standing for two processes.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient

from syn_adapters.advisory_locks import (
    ROLLUP_SCHEMA_LOCK_KEY,
    ROLLUP_STARTUP_LOCK_KEY,
    RUN_QUEUE_SCHEMA_LOCK_KEY,
    USAGE_ROLLUP_SCHEMA_LOCK_KEY,
    inventory_schedule_lock_key,
    try_session_advisory_lock,
)
from syn_adapters.session_inventory.memory_jobs import (
    InMemoryInventorySchedulingGuard,
    InMemorySessionInventory,
)
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.agent_sessions import (
    EvidenceBatch,
    InventoryReconciliationAggregate,
    PendingEvidence,
    RunIdentity,
    SchedulePendingInventoryHandler,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import SessionEvidence
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
    SessionEvidenceWritePort,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

    from syn_domain.contexts.agent_sessions import InventorySnapshot
    from syn_domain.contexts.agent_sessions.ports.InventorySchedulingGuardPort import (
        InventorySchedulingGuardPort,
    )


class _Outbox(SessionEvidenceWritePort, Protocol):
    async def watermark(self, run: RunIdentity) -> int: ...


@dataclass
class _Evidence:
    """The one-row-per-run outbox, as the Postgres adapter keeps it."""

    watermarks: dict[RunIdentity, int] = field(default_factory=dict)
    dispatched: dict[RunIdentity, int] = field(default_factory=dict)

    async def append(self, batch: EvidenceBatch) -> int:
        run = batch.evidence.run
        self.watermarks[run] = self.watermarks.get(run, 0) + 1
        return self.watermarks[run]

    async def watermark(self, run: RunIdentity) -> int:
        return self.watermarks.get(run, 0)

    async def pending(self, *, limit: int = 100) -> tuple[PendingEvidence, ...]:
        return tuple(
            PendingEvidence(run=run, watermark=mark)
            for run, mark in self.watermarks.items()
            if mark > self.dispatched.get(run, 0)
        )[:limit]

    async def acknowledge_dispatch(self, item: PendingEvidence) -> None:
        self.dispatched[item.run] = max(self.dispatched.get(item.run, 0), item.watermark)

    async def requeue(self, item: PendingEvidence) -> None:
        self.dispatched[item.run] = min(self.dispatched.get(item.run, 0), item.watermark - 1)


class _PausedInventory(InMemorySessionInventory):
    """Parks the first ``head`` read: after the open-job check, before the schedule."""

    def __init__(self) -> None:
        super().__init__()
        self.checked = asyncio.Event()
        self.resume = asyncio.Event()

    async def head(self, run: RunIdentity) -> InventorySnapshot | None:
        if not self.checked.is_set():
            self.checked.set()
            await self.resume.wait()
        return await super().head(run)


class _NoJobs:
    """Neither manager has seen a job projected: both see the run as free."""

    async def latest(self, run: RunIdentity) -> None:
        return None


def _batch(run: RunIdentity, name: str) -> EvidenceBatch:
    return EvidenceBatch(batch_id=name, producer_id="host", evidence=SessionEvidence(run=run))


async def _job_streams(client: MemoryEventStoreClient) -> set[str]:
    page, _, _ = await client.read_all(from_global_nonce=0, max_count=10_000)
    return {envelope.metadata.aggregate_id for envelope in page}


async def _race(
    evidence: _Outbox,
    run: RunIdentity,
    guard_a: InventorySchedulingGuardPort,
    guard_b: InventorySchedulingGuardPort,
) -> set[str]:
    """A checks and pauses at watermark 1; B ticks at watermark 2; A resumes."""
    client = MemoryEventStoreClient()
    repository = RepositoryAdapter(
        EventStoreRepository(
            client,
            InventoryReconciliationAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "InventoryReconciliation",
        )
    )
    paused = _PausedInventory()
    jobs = _NoJobs()
    manager_a = SchedulePendingInventoryHandler(evidence, paused, repository, jobs, guard_a)  # type: ignore[arg-type]  # _NoJobs is latest() only
    manager_b = SchedulePendingInventoryHandler(  # type: ignore[arg-type]  # _NoJobs is latest() only
        evidence, InMemorySessionInventory(), repository, jobs, guard_b
    )
    assert await evidence.append(_batch(run, "first")) == 1
    tick_a = asyncio.create_task(manager_a.handle())
    await asyncio.wait_for(paused.checked.wait(), timeout=5)
    assert await evidence.append(_batch(run, "second")) == 2
    await asyncio.wait_for(manager_b.handle(), timeout=5)
    paused.resume.set()
    await asyncio.wait_for(tick_a, timeout=5)
    return await _job_streams(client)


@pytest.mark.unit
async def test_two_managers_racing_one_run_open_exactly_one_job() -> None:
    run = RunIdentity(source_instance_id="guard-test", execution_id="run")
    guard = InMemoryInventorySchedulingGuard()
    evidence = _Evidence()

    streams = await _race(evidence, run, guard, guard)

    assert len(streams) == 1
    # A scheduled watermark 1; B's watermark-2 wakeup was skipped, not dropped.
    assert await evidence.pending() == (PendingEvidence(run=run, watermark=2),)


@pytest.mark.unit
async def test_a_run_whose_guard_is_held_is_skipped_and_its_wakeup_kept() -> None:
    held = RunIdentity(source_instance_id="guard-test", execution_id="held")
    free = RunIdentity(source_instance_id="guard-test", execution_id="free")
    guard = InMemoryInventorySchedulingGuard()
    evidence = _Evidence()
    await evidence.append(_batch(held, "held"))
    await evidence.append(_batch(free, "free"))
    client = MemoryEventStoreClient()
    repository = RepositoryAdapter(
        EventStoreRepository(
            client,
            InventoryReconciliationAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "InventoryReconciliation",
        )
    )
    handler = SchedulePendingInventoryHandler(
        evidence,
        InMemorySessionInventory(),
        repository,
        _NoJobs(),  # type: ignore[arg-type]  # latest() only
        guard,
    )

    async with guard.hold(held) as taken:
        assert taken
        await handler.handle()

    # The held run was neither scheduled nor acknowledged; the free run was both.
    assert await evidence.pending() == (PendingEvidence(run=held, watermark=1),)
    page, _, _ = await client.read_all(from_global_nonce=0, max_count=100)
    assert {envelope.event.model_dump()["execution_id"] for envelope in page} == {"free"}


@pytest.mark.unit
def test_per_run_keys_are_stable_distinct_and_clear_of_startup_keys() -> None:
    a = inventory_schedule_lock_key("source", "run-a")
    assert a == inventory_schedule_lock_key("source", "run-a")
    assert a != inventory_schedule_lock_key("source", "run-b")
    # The separator cannot be forged by moving characters between the fields.
    assert inventory_schedule_lock_key("a:b", "c") != inventory_schedule_lock_key("a", "b:c")
    startup = {
        ROLLUP_SCHEMA_LOCK_KEY,
        ROLLUP_STARTUP_LOCK_KEY,
        RUN_QUEUE_SCHEMA_LOCK_KEY,
        USAGE_ROLLUP_SCHEMA_LOCK_KEY,
    }
    assert a not in startup


class _OneShotConnection:
    def __init__(self, *, granted: bool) -> None:
        self.granted = granted
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchval(self, query: str, *args: object) -> object:
        self.calls.append((query, args))
        return self.granted

    async def execute(self, query: str, *args: object) -> object:
        self.calls.append((query, args))
        return None


@pytest.mark.unit
async def test_try_lock_asks_once_and_releases_only_what_it_took() -> None:
    refused = _OneShotConnection(granted=False)
    async with try_session_advisory_lock(refused, 7) as held:
        assert not held
    # One attempt, never a retry and never a blocking pg_advisory_lock.
    assert refused.calls == [("SELECT pg_try_advisory_lock($1)", (7,))]

    granted = _OneShotConnection(granted=True)
    async with try_session_advisory_lock(granted, 7) as held:
        assert held
    assert granted.calls[-1] == ("SELECT pg_advisory_unlock($1)", (7,))


@pytest.fixture
async def outbox(db_pool: asyncpg.Pool) -> AsyncIterator[_Outbox]:
    from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence

    store = PostgresSessionEvidence(db_pool)
    await store.ensure_ready()
    yield store


@asynccontextmanager
async def _guard_on(pool: asyncpg.Pool) -> AsyncIterator[InventorySchedulingGuardPort]:
    from syn_adapters.session_inventory.scheduling_guard import PostgresInventorySchedulingGuard

    yield PostgresInventorySchedulingGuard(pool)  # type: ignore[arg-type]  # asyncpg.Pool satisfies Pool


@pytest.mark.integration
async def test_two_managers_on_postgres_open_exactly_one_job_per_run(
    outbox: _Outbox, db_pool: asyncpg.Pool
) -> None:
    run = RunIdentity(source_instance_id=f"guard-test-{uuid4()}", execution_id="run")
    # One guard per manager: each hold() takes its own pooled connection, so
    # the two managers are two Postgres sessions, as two processes would be.
    async with _guard_on(db_pool) as guard_a, _guard_on(db_pool) as guard_b:
        streams = await _race(outbox, run, guard_a, guard_b)

    assert len(streams) == 1
    pending = [item for item in await outbox.pending(limit=500) if item.run == run]
    assert pending == [PendingEvidence(run=run, watermark=2)]
