"""The inventory ProcessManager makes progress or stays quiet; it never spins (#1528).

Drives the real InventoryReconciliationProcessManager, InventoryWork, scheduler
and step handler against the real event-sourced repository (memory event store)
and the guarded in-memory jobs and inventory adapters, which mirror the Postgres
claim, lease, re-arm and publication rules: a job publishes only a staged
snapshot whose revision, resolver and watermark match it, against the run's
current head. Events reach the manager only when ``_Harness.deliver()`` says so,
which is how projection lag is reproduced: the store runs ahead of the to-do
rows exactly as it did in production.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.session_inventory.memory_jobs import (
    InMemorySessionInventory,
    InMemorySessionInventoryJobs,
    Publication,
)
from syn_adapters.session_inventory.runtime import InventoryWork
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.agent_sessions import (
    BuildInventorySnapshotHandler,
    EvidenceBatch,
    EvidencePage,
    EvidenceReference,
    InventoryNodeRef,
    InventoryReconciliationAggregate,
    InventoryReconciliationProcessManager,
    InventoryStepHandler,
    NodeEvidence,
    PendingEvidence,
    RunIdentity,
    SchedulePendingInventoryHandler,
    StoredEvidenceBatch,
)
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationStage,
    ReconciliationState,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import SessionEvidence

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import InventoryJobLease, InventoryStepOutcome

pytestmark = pytest.mark.unit

SOURCE = "drain-test"
RETRY_SECONDS = 10
LEASE_SECONDS = 60
# Production: 31 open jobs, max_jobs_per_tick=2 (SessionInventorySettings default).
STALE_JOBS = 31
MAX_JOBS = 2


@dataclass
class _Evidence:
    """Evidence journal and its one-row-per-run outbox, as the Postgres adapter keeps them."""

    batches: dict[RunIdentity, list[StoredEvidenceBatch]] = field(default_factory=dict)
    dispatched: dict[RunIdentity, int] = field(default_factory=dict)

    async def append(self, batch: EvidenceBatch) -> int:
        stored = self.batches.setdefault(batch.evidence.run, [])
        stored.append(StoredEvidenceBatch(sequence=len(stored) + 1, batch=batch))
        return len(stored)

    async def watermark(self, run: RunIdentity) -> int:
        return len(self.batches.get(run, ()))

    async def read(
        self, run: RunIdentity, watermark: int, *, after: int = 0, limit: int = 100
    ) -> EvidencePage:
        window = self.batches.get(run, [])[after:watermark]
        items = tuple(window[:limit])
        more = len(window) > limit
        return EvidencePage(
            watermark=watermark, items=items, next_after=items[-1].sequence if more else None
        )

    async def pending(self, *, limit: int = 100) -> tuple[PendingEvidence, ...]:
        return tuple(
            PendingEvidence(run=run, watermark=len(stored))
            for run, stored in self.batches.items()
            if len(stored) > self.dispatched.get(run, 0)
        )[:limit]

    async def acknowledge_dispatch(self, item: PendingEvidence) -> None:
        self.dispatched[item.run] = max(self.dispatched.get(item.run, 0), item.watermark)

    async def requeue(self, item: PendingEvidence) -> None:
        self.dispatched[item.run] = min(self.dispatched.get(item.run, 0), item.watermark - 1)


@dataclass
class _CountingWork:
    """Records which job each execute ran for; behaviour is the real InventoryWork's."""

    inner: InventoryWork
    executed: list[str] = field(default_factory=list)

    async def schedule(self) -> None:
        await self.inner.schedule()

    async def execute(self, lease: InventoryJobLease) -> InventoryStepOutcome:
        self.executed.append(lease.job.job_id)
        return await self.inner.execute(lease)


class _Harness:
    def __init__(self) -> None:
        self.now = 0.0
        self.inventory = InMemorySessionInventory()
        self.jobs = InMemorySessionInventoryJobs(self.inventory, clock=lambda: self.now)
        self.client = MemoryEventStoreClient()
        self.repository = RepositoryAdapter(
            EventStoreRepository(
                self.client,
                InventoryReconciliationAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "InventoryReconciliation",
            )
        )
        self.evidence = _Evidence()
        builder = BuildInventorySnapshotHandler(
            self.evidence, self.inventory, max_evidence_records=100_000, max_evidence_batches=10_000
        )
        self.scheduler = SchedulePendingInventoryHandler(
            self.evidence, self.inventory, self.repository, self.jobs
        )
        self.step = InventoryStepHandler(
            self.repository, self.jobs, builder, self.evidence, lease_seconds=LEASE_SECONDS
        )
        self.work = _CountingWork(InventoryWork(scheduler=self.scheduler, step=self.step))
        self.manager = InventoryReconciliationProcessManager(
            self.jobs,
            self.work,
            lease_seconds=LEASE_SECONDS,
            retry_seconds=RETRY_SECONDS,
            max_jobs_per_tick=MAX_JOBS,
        )
        self.checkpoints = MemoryCheckpointStore()
        self._delivered = 0
        self.call_ms: list[float] = []

    async def events(self) -> int:
        page, _, _ = await self.client.read_all(from_global_nonce=0, max_count=100_000)
        return len(page)

    async def deliver(self) -> None:
        """Let the projection catch up with everything the store holds."""
        page, _, _ = await self.client.read_all(
            from_global_nonce=self._delivered, max_count=100_000
        )
        for envelope in page:
            # The real store stamps event_type on delivery; the memory client does not.
            metadata = envelope.metadata.model_copy(
                update={"event_type": envelope.event.event_type}
            )
            await self.manager.handle_event(
                envelope.model_copy(update={"metadata": metadata}), self.checkpoints
            )
            self._delivered = (envelope.metadata.global_nonce or 0) + 1

    async def tick(self) -> int:
        """One process_pending call, after the 10s blind retry would have expired."""
        self.now += RETRY_SECONDS + 1
        started = time.perf_counter()
        processed = await self.manager.process_pending()
        self.call_ms.append((time.perf_counter() - started) * 1000)
        return processed

    async def crashed_worker_steps(self) -> None:
        """A previous worker ran every due step and died before releasing its leases.

        The steps are the real ones: snapshots are built and staged and the
        PUBLISHING events are saved. Only delivery to this manager's projection
        is withheld, and the dead worker's leases are left to expire.
        """
        while (lease := await self.jobs.claim(lease_seconds=LEASE_SECONDS)) is not None:
            await self.step.handle(lease)
        self.now += LEASE_SECONDS + 1

    async def state_of(self, job_id: str) -> ReconciliationState:
        aggregate = await self.repository.get_by_id(job_id)
        assert aggregate is not None and aggregate.state is not None
        return aggregate.state

    async def stage_of(self, job_id: str) -> ReconciliationStage:
        return (await self.state_of(job_id)).stage


def _run(execution_id: str) -> RunIdentity:
    return RunIdentity(source_instance_id=SOURCE, execution_id=execution_id)


async def _add_evidence(harness: _Harness, run: RunIdentity, records: int = 1) -> None:
    """One batch of ``records`` distinct transcript nodes, as a producer appends them."""
    batch_id = str(uuid4())
    nodes = tuple(
        NodeEvidence(
            node=InventoryNodeRef(
                kind="transcript",
                source_instance_id=run.source_instance_id,
                harness="fake",
                local_id=f"{batch_id}-{n}",
            ),
            evidence=EvidenceReference(
                evidence_id=f"{batch_id}-{n}",
                producer_id="producer",
                source_revision="1",
                locator=f"{batch_id}-{n}",
                extractor_version="test/1",
            ),
        )
        for n in range(records)
    )
    await harness.evidence.append(
        EvidenceBatch(
            batch_id=batch_id,
            producer_id="producer",
            evidence=SessionEvidence(run=run, nodes=nodes),
        )
    )


async def _jobs_for(harness: _Harness, run: RunIdentity) -> list[str]:
    page, _, _ = await harness.client.read_all(from_global_nonce=0, max_count=100_000)
    return sorted(
        {
            envelope.metadata.aggregate_id
            for envelope in page
            if getattr(envelope.event, "execution_id", None) == run.execution_id
        }
    )


async def _stale_jobs(harness: _Harness, count: int = STALE_JOBS) -> list[str]:
    """``count`` jobs whose store has moved on to PUBLISHING while their rows say PENDING."""
    runs = [_run(f"run-{n}") for n in range(count)]
    for run in runs:
        await _add_evidence(harness, run)
    await harness.scheduler.handle()
    await harness.deliver()
    await harness.crashed_worker_steps()
    ids = [job_id for run in runs for job_id in await _jobs_for(harness, run)]
    assert len(ids) == count
    for job_id in ids:
        assert await harness.stage_of(job_id) is ReconciliationStage.PUBLISHING
        row = await harness.jobs.get(job_id)
        assert row is not None and row.state.stage is ReconciliationStage.PENDING
    return ids


async def test_stale_jobs_are_not_progress_and_are_not_retried_until_their_event_arrives() -> None:
    harness = _Harness()
    ids = await _stale_jobs(harness)
    events = await harness.events()

    # Production logged items_processed: 2 on every tick, forever. Ticks far
    # past the 10s retry: every stale job is looked at once, then left alone.
    results = [await harness.tick() for _ in range(STALE_JOBS * 2)]

    assert results == [0] * len(results)
    assert sorted(harness.work.executed) == sorted(ids)
    assert await harness.events() == events  # idle means quiet: nothing emitted

    # The projection observes each job's newer step: it is re-armed and
    # publishes the snapshot the dead worker staged, as the run's first head.
    await harness.deliver()
    progress = [await harness.tick() for _ in range(STALE_JOBS)]
    assert sum(progress) == STALE_JOBS
    states = [await harness.state_of(job_id) for job_id in ids]
    assert [state.stage for state in states] == [ReconciliationStage.COMPLETED] * STALE_JOBS
    assert sorted(harness.inventory.publications, key=lambda p: str(p.snapshot_id)) == sorted(
        (
            Publication(
                run=state.request.run,
                snapshot_id=state.request.snapshot_id,
                parent_snapshot_id=None,
                revision_sequence=1,
            )
            for state in states
        ),
        key=lambda p: str(p.snapshot_id),
    )
    for state in states:
        head = await harness.inventory.head(state.request.run)
        assert head is not None
        assert (head.snapshot_id, head.revision) == (state.request.snapshot_id, state.revision)

    # Terminal events arrive; nothing is left to do and nothing is emitted.
    await harness.deliver()
    events = await harness.events()
    assert [await harness.tick() for _ in range(5)] == [0] * 5
    assert await harness.events() == events


async def test_a_step_waits_for_its_own_event_instead_of_reclaiming_the_stale_row() -> None:
    harness = _Harness()
    run = _run("own-event")
    await _add_evidence(harness, run)
    await harness.scheduler.handle()
    await harness.deliver()
    (job_id,) = await _jobs_for(harness, run)

    assert await harness.tick() == 1  # pending -> publishing, saved to the store
    executed = len(harness.work.executed)
    assert [await harness.tick() for _ in range(5)] == [0] * 5
    assert len(harness.work.executed) == executed  # not re-claimed while unobserved

    await harness.deliver()
    assert await harness.tick() == 1  # publishing -> completed
    assert await harness.stage_of(job_id) is ReconciliationStage.COMPLETED


async def test_evidence_arriving_during_an_open_job_is_coalesced_into_the_next_one() -> None:
    harness = _Harness()
    run = _run("busy")
    await _add_evidence(harness, run)
    await harness.tick()  # schedules job A at watermark 1 (store only)
    await harness.deliver()
    (first,) = await _jobs_for(harness, run)

    # Three more evidence batches while A works through pending -> publishing
    # -> completed. Before #1528 every tick minted a job with A's expected head
    # (four jobs here), each able to end only as publication_superseded.
    for _ in range(3):
        await _add_evidence(harness, run)
        await harness.tick()
        await harness.deliver()
    for _ in range(4):
        await harness.tick()
        await harness.deliver()

    assert await harness.stage_of(first) is ReconciliationStage.COMPLETED
    jobs = await _jobs_for(harness, run)
    assert len(jobs) == 2
    (second,) = (job_id for job_id in jobs if job_id != first)
    a = (await harness.state_of(first)).request
    b = await harness.state_of(second)
    assert b.stage is ReconciliationStage.COMPLETED
    assert b.request.evidence_watermark == 4
    # The coalesced job was scheduled against the head A published, so the
    # publication's head swap accepts it: A, then B on top of A.
    assert (a.expected_head, b.request.expected_head) == (None, a.snapshot_id)
    assert harness.inventory.publications == [
        Publication(
            run=run, snapshot_id=a.snapshot_id, parent_snapshot_id=None, revision_sequence=1
        ),
        Publication(
            run=run,
            snapshot_id=b.request.snapshot_id,
            parent_snapshot_id=a.snapshot_id,
            revision_sequence=2,
        ),
    ]
    head = await harness.inventory.head(run)
    assert head is not None
    assert (head.snapshot_id, head.evidence_watermark) == (b.request.snapshot_id, 4)


async def test_process_pending_logs_wall_time_per_stage(caplog: pytest.LogCaptureFixture) -> None:
    harness = _Harness()
    await _stale_jobs(harness)
    logger = "syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.projection"
    with caplog.at_level(logging.DEBUG, logger=logger):
        await harness.tick()
    records = [record for record in caplog.records if record.name == logger]
    assert [getattr(record, "stage", None) for record in records] == [
        "schedule",
        "execute",
        "execute",
    ]
    assert [getattr(record, "job_id", None) for record in records[1:]] == harness.work.executed
    assert all(getattr(record, "duration_ms", -1.0) >= 0 for record in records)
