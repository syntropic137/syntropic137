"""Inventory scheduling is atomic per run across managers (#1534).

Two ``SchedulePendingInventoryHandler`` instances stand for two inventory
managers on one database. Manager A is paused after its open-job check and
before it schedules; evidence then advances the run's watermark and manager B
ticks. Without a per-run guard both pass the check and the store gets two jobs
for one run with different identities (watermark 1 and watermark 2).

The guard alone is not enough (#2254): a job is projected after it is saved,
so a manager that re-takes the guard before then reads the run as free. Every
race here therefore runs on a job projection that never catches up.

The unit half runs on in-memory twins. The integration half runs the same race
on the real Postgres outbox and the real advisory-lock guard, two pooled
connections standing for two processes.
"""

from __future__ import annotations

import asyncio
import contextlib
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
    ReconciliationStage,
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


@dataclass
class _RunScoped:
    """The outbox as one run sees it: writes go through, ``pending`` is the run's.

    The Postgres outbox is shared with every other test on the stack, and its
    ``pending`` is ordered by run. Unscoped, an unrelated earlier wakeup would be
    the one manager A parks on, and the race would never touch this run.
    """

    outbox: _Outbox
    run: RunIdentity

    async def append(self, batch: EvidenceBatch) -> int:
        return await self.outbox.append(batch)

    async def watermark(self, run: RunIdentity) -> int:
        return await self.outbox.watermark(run)

    async def pending(self, *, limit: int = 100) -> tuple[PendingEvidence, ...]:
        # Paged until exhausted, so the run's row is found behind any number of others.
        found: list[PendingEvidence] = []
        page_size = 500
        while True:
            page = await self.outbox.pending(limit=page_size)
            found = [item for item in page if item.run == self.run]
            if found or len(page) < page_size:
                return tuple(found)[:limit]
            page_size *= 2

    async def acknowledge_dispatch(self, item: PendingEvidence) -> None:
        await self.outbox.acknowledge_dispatch(item)

    async def requeue(self, item: PendingEvidence) -> None:
        await self.outbox.requeue(item)


class _PausedInventory(InMemorySessionInventory):
    """Parks the first ``head`` read of ``run``: after the open-job check, before the schedule."""

    def __init__(self, run: RunIdentity) -> None:
        super().__init__()
        self.run = run
        self.checked = asyncio.Event()
        self.resume = asyncio.Event()

    async def head(self, run: RunIdentity) -> InventorySnapshot | None:
        if run == self.run and not self.checked.is_set():
            self.checked.set()
            await self.resume.wait()
        return await super().head(run)


class _NoJobs:
    """Neither manager has seen a job projected: both see the run as free."""

    async def latest(self, run: RunIdentity) -> None:
        return None


def _batch(run: RunIdentity, name: str) -> EvidenceBatch:
    return EvidenceBatch(batch_id=name, producer_id="host", evidence=SessionEvidence(run=run))


async def _job_streams(client: MemoryEventStoreClient, run: RunIdentity) -> set[str]:
    # Only this run's jobs: on the shared Postgres outbox the handler also
    # schedules wakeups left pending by earlier tests (each race leaves its
    # watermark-2 wakeup pending by design), which are not this race's jobs.
    page, _, _ = await client.read_all(from_global_nonce=0, max_count=10_000)
    return {
        envelope.metadata.aggregate_id
        for envelope in page
        if envelope.event.model_dump().get("source_instance_id") == run.source_instance_id
        and envelope.event.model_dump().get("execution_id") == run.execution_id
    }


async def _race(
    evidence: _Outbox,
    run: RunIdentity,
    guard_a: InventorySchedulingGuardPort,
    guard_b: InventorySchedulingGuardPort,
) -> set[str]:
    """A checks and pauses at watermark 1; B ticks at watermark 2; A resumes."""
    evidence = _RunScoped(evidence, run)
    client = MemoryEventStoreClient()
    repository = RepositoryAdapter(
        EventStoreRepository(
            client,
            InventoryReconciliationAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "InventoryReconciliation",
        )
    )
    paused = _PausedInventory(run)
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
    # B re-takes the free guard while A's job is still unprojected (#2254).
    await asyncio.wait_for(manager_b.handle(), timeout=5)
    return await _job_streams(client, run)


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
async def test_the_race_is_run_on_its_own_run_behind_an_unrelated_earlier_wakeup() -> None:
    # The shared Postgres outbox may hold other tests' wakeups, ordered first.
    earlier = RunIdentity(source_instance_id="guard-test-0000", execution_id="run")
    run = RunIdentity(source_instance_id="guard-test-ffff", execution_id="run")
    guard = InMemoryInventorySchedulingGuard()
    evidence = _Evidence()
    await evidence.append(_batch(earlier, "earlier"))

    streams = await _race(evidence, run, guard, guard)

    assert len(streams) == 1
    pending = [item for item in await evidence.pending() if item.run == run]
    assert pending == [PendingEvidence(run=run, watermark=2)]
    # Never touched: the race consumed only its own run.
    assert PendingEvidence(run=earlier, watermark=1) in await evidence.pending()


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

    async with guard.hold(held) as schedule:
        assert schedule is not None
        await handler.handle()

    # The held run was neither scheduled nor acknowledged; the free run was both.
    assert await evidence.pending() == (PendingEvidence(run=held, watermark=1),)
    page, _, _ = await client.read_all(from_global_nonce=0, max_count=100)
    assert {envelope.event.model_dump()["execution_id"] for envelope in page} == {"free"}


def _store() -> tuple[MemoryEventStoreClient, RepositoryAdapter[InventoryReconciliationAggregate]]:
    client = MemoryEventStoreClient()
    return client, RepositoryAdapter(
        EventStoreRepository(
            client,
            InventoryReconciliationAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
            "InventoryReconciliation",
        )
    )


@pytest.mark.unit
async def test_a_job_scheduled_but_not_yet_projected_still_holds_its_run() -> None:
    # #2254: one manager schedules and releases the guard; evidence advances;
    # the next tick takes the guard before the job reaches the projection.
    run = RunIdentity(source_instance_id="guard-test", execution_id="lagging")
    guard = InMemoryInventorySchedulingGuard()
    evidence = _Evidence()
    client, repository = _store()
    manager = SchedulePendingInventoryHandler(
        evidence,
        InMemorySessionInventory(),
        repository,
        _NoJobs(),  # type: ignore[arg-type]  # latest() only
        guard,
    )
    await evidence.append(_batch(run, "first"))
    await manager.handle()
    await evidence.append(_batch(run, "second"))

    await manager.handle()

    assert len(await _job_streams(client, run)) == 1
    # Coalesced, not dropped: the watermark-2 wakeup waits for the open job.
    assert await evidence.pending() == (PendingEvidence(run=run, watermark=2),)


class _LostAppend(RepositoryAdapter[InventoryReconciliationAggregate]):
    """The next ``save_new`` fails at the transport, its outcome unknown to the caller.

    ``commit_late`` models the store committing that append after the caller
    has given up on it; without it, the append simply never landed.
    """

    def __init__(self, client: MemoryEventStoreClient) -> None:
        super().__init__(
            EventStoreRepository(
                client,
                InventoryReconciliationAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "InventoryReconciliation",
            )
        )
        self.lose_next = True
        self.lost: list[InventoryReconciliationAggregate] = []

    async def save_new(self, aggregate: InventoryReconciliationAggregate) -> None:
        if self.lose_next:
            self.lose_next = False
            self.lost.append(aggregate)
            raise ConnectionError("Append transport lost before response")
        await super().save_new(aggregate)

    async def commit_late(self) -> None:
        # The late commit is the same append, so it lands only if the stream is
        # still new; a retry that already wrote it makes the store refuse it.
        with contextlib.suppress(Exception):
            await super().save_new(self.lost.pop())


async def _open_streams(
    client: MemoryEventStoreClient,
    repository: RepositoryAdapter[InventoryReconciliationAggregate],
    run: RunIdentity,
) -> set[str]:
    """This run's jobs that are PENDING or PUBLISHING, read from their streams."""
    open_jobs: set[str] = set()
    for job_id in await _job_streams(client, run):
        aggregate = await repository.get_by_id(job_id)
        assert aggregate is not None
        assert aggregate.state is not None
        if aggregate.state.stage in (ReconciliationStage.PENDING, ReconciliationStage.PUBLISHING):
            open_jobs.add(job_id)
    return open_jobs


async def _lose_first_save(
    run: RunIdentity,
) -> tuple[
    InMemoryInventorySchedulingGuard,
    _Evidence,
    MemoryEventStoreClient,
    _LostAppend,
    SchedulePendingInventoryHandler,
]:
    """Watermark 1's job is recorded, its save is lost, then evidence advances."""
    guard = InMemoryInventorySchedulingGuard()
    evidence = _Evidence()
    client = MemoryEventStoreClient()
    repository = _LostAppend(client)
    manager = SchedulePendingInventoryHandler(
        evidence,
        InMemorySessionInventory(),
        repository,
        _NoJobs(),  # type: ignore[arg-type]  # latest() only
        guard,
    )
    await evidence.append(_batch(run, "first"))
    with pytest.raises(ConnectionError):
        await manager.handle()
    # The guard was released, the wakeup kept, and nothing is readable yet.
    assert run not in guard.held
    assert await evidence.pending() == (PendingEvidence(run=run, watermark=1),)
    assert await _job_streams(client, run) == set()
    await evidence.append(_batch(run, "second"))
    return guard, evidence, client, repository, manager


@pytest.mark.unit
async def test_a_save_whose_outcome_is_unknown_is_retried_never_replaced() -> None:
    # #2254: a failed Append may still commit. Scheduling a successor at the
    # newer watermark because the old stream reads empty opens two jobs.
    run = RunIdentity(source_instance_id="guard-test", execution_id="ambiguous")
    _, evidence, client, repository, manager = await _lose_first_save(run)
    lost = repository.lost[0].id

    await manager.handle()

    assert await _open_streams(client, repository, run) == {lost}
    await repository.commit_late()
    assert await _open_streams(client, repository, run) == {lost}
    # Coalesced behind the retried job, not dispatched past it.
    assert await evidence.pending() == (PendingEvidence(run=run, watermark=2),)
    await manager.handle()
    assert await _open_streams(client, repository, run) == {lost}


@pytest.mark.unit
async def test_a_save_that_committed_late_still_holds_its_run() -> None:
    run = RunIdentity(source_instance_id="guard-test", execution_id="late")
    _, evidence, client, repository, manager = await _lose_first_save(run)
    lost = repository.lost[0].id
    await repository.commit_late()

    await manager.handle()

    assert await _open_streams(client, repository, run) == {lost}
    assert await evidence.pending() == (PendingEvidence(run=run, watermark=2),)


@pytest.mark.unit
async def test_a_save_that_never_landed_does_not_strand_its_run() -> None:
    # Definitely unsaved: the recorded request is saved by the next holder, so
    # the run has its job and the newer evidence follows it, never stranded.
    run = RunIdentity(source_instance_id="guard-test", execution_id="crashed")
    guard, evidence, client, repository, manager = await _lose_first_save(run)
    recorded = guard.scheduled[run]
    repository.lost.clear()

    await manager.handle()

    assert await _job_streams(client, run) == {recorded.aggregate_id}
    reloaded = await repository.get_by_id(recorded.aggregate_id)
    assert reloaded is not None
    assert reloaded.state is not None
    assert reloaded.state.request == recorded.request
    assert await evidence.pending() == (PendingEvidence(run=run, watermark=2),)


class _SizedPool:
    """``max_size`` connections; an acquire past that waits, as asyncpg's does."""

    def __init__(self, max_size: int) -> None:
        self._max_size = max_size
        self._slots = asyncio.Semaphore(max_size)

    def get_max_size(self) -> int:
        return self._max_size

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_OneShotConnection]:
        async with self._slots:
            yield _OneShotConnection(granted=True)


@pytest.mark.unit
async def test_a_pool_too_small_for_the_critical_section_is_refused_at_wiring() -> None:
    from syn_adapters.session_inventory.scheduling_guard import PostgresInventorySchedulingGuard

    run = RunIdentity(source_instance_id="guard-test", execution_id="pool")

    async def wire_and_schedule(pool: _SizedPool) -> None:
        guard = PostgresInventorySchedulingGuard(pool)  # type: ignore[arg-type]  # Pool double
        async with guard.hold(run) as schedule:
            assert schedule is not None
            # What the open-job check does next: a second connection, same pool.
            async with pool.acquire():
                pass

    # Never a hang (#2254): a size-1 pool is refused before anything is held.
    with pytest.raises(ValueError, match="at least 2 connections, got 1"):
        await asyncio.wait_for(wire_and_schedule(_SizedPool(1)), timeout=2)
    await asyncio.wait_for(wire_and_schedule(_SizedPool(2)), timeout=2)


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
