"""The inventory ProcessManager makes progress or stays quiet; it never spins (#1528).

Drives the real InventoryReconciliationProcessManager, InventoryWork, scheduler
and step handler against the real event-sourced repository (memory event store)
and the guarded in-memory jobs adapter, which mirrors the Postgres claim, lease
and re-arm rules. Events reach the manager only when ``_Harness.deliver()`` says
so, which is how projection lag is reproduced: the store runs ahead of the
to-do rows exactly as it did in production.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.client.memory import MemoryEventStoreClient
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

from syn_adapters.session_inventory.memory_jobs import InMemorySessionInventoryJobs
from syn_adapters.session_inventory.runtime import InventoryWork
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.agent_sessions import (
    BuildInventorySnapshotHandler,
    EvidenceBatch,
    EvidencePage,
    InventoryReconciliationAggregate,
    InventoryReconciliationProcessManager,
    InventoryStepHandler,
    PendingEvidence,
    RunIdentity,
    SchedulePendingInventoryHandler,
    StoredEvidenceBatch,
)
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
    ReconciliationStage,
)
from syn_domain.contexts.agent_sessions.domain.commands.AdvanceInventoryReconciliationCommand import (
    AdvanceInventoryReconciliationCommand,
)
from syn_domain.contexts.agent_sessions.domain.commands.RequestInventoryReconciliationCommand import (
    RequestInventoryReconciliationCommand,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import SessionEvidence
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    RESOLVER_VERSION,
)

if TYPE_CHECKING:
    from uuid import UUID

    from syn_domain.contexts.agent_sessions import (
        InventoryItem,
        InventoryJobLease,
        InventorySnapshot,
        InventoryStepOutcome,
        ItemKind,
    )

pytestmark = pytest.mark.unit

SOURCE = "drain-test"
RETRY_SECONDS = 10
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
        items = tuple(self.batches.get(run, [])[after:watermark][:limit])
        return EvidencePage(watermark=watermark, items=items)

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
class _Inventory:
    """Staging only. Heads are not modelled, so every job sees ``expected_head=None``."""

    staged: list[UUID] = field(default_factory=list)

    async def head(self, run: RunIdentity) -> InventorySnapshot | None:  # noqa: ARG002
        return None

    async def stage(self, snapshot: InventorySnapshot) -> None:
        self.staged.append(snapshot.snapshot_id)

    async def append(
        self,
        run: RunIdentity,
        snapshot_id: UUID,
        kind: ItemKind,
        start: int,
        items: tuple[InventoryItem, ...],
    ) -> None:
        return None


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
        self.jobs = InMemorySessionInventoryJobs(clock=lambda: self.now)
        self.client = MemoryEventStoreClient()
        self.repository = RepositoryAdapter(
            EventStoreRepository(
                self.client,
                InventoryReconciliationAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "InventoryReconciliation",
            )
        )
        self.evidence = _Evidence()
        self.inventory = _Inventory()
        builder = BuildInventorySnapshotHandler(
            self.evidence, self.inventory, max_evidence_records=1000, max_evidence_batches=1000
        )
        self.work = _CountingWork(
            InventoryWork(
                scheduler=SchedulePendingInventoryHandler(
                    self.evidence, self.inventory, self.repository, self.jobs
                ),
                step=InventoryStepHandler(
                    self.repository, self.jobs, builder, self.evidence, lease_seconds=60
                ),
            )
        )
        self.manager = InventoryReconciliationProcessManager(
            self.jobs,
            self.work,
            lease_seconds=60,
            retry_seconds=RETRY_SECONDS,
            max_jobs_per_tick=MAX_JOBS,
        )
        self.checkpoints = MemoryCheckpointStore()
        self._delivered = 0

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
        return await self.manager.process_pending()

    async def request(self, run: RunIdentity) -> str:
        job_id = str(uuid4())
        aggregate = InventoryReconciliationAggregate()
        aggregate.request(
            RequestInventoryReconciliationCommand(
                aggregate_id=job_id,
                request=ReconciliationRequest(
                    run=run,
                    evidence_watermark=0,
                    expected_head=None,
                    snapshot_id=uuid4(),
                    resolver_version=RESOLVER_VERSION,
                ),
            )
        )
        await self.repository.save_new(aggregate)
        return job_id

    async def advance_in_store(self, job_id: str) -> None:
        """A step whose event the projection has not observed yet."""
        aggregate = await self.repository.get_by_id(job_id)
        assert aggregate is not None
        aggregate.advance(
            AdvanceInventoryReconciliationCommand(
                aggregate_id=job_id, stage=ReconciliationStage.PUBLISHING, revision="r1"
            )
        )
        await self.repository.save(aggregate)

    async def stage_of(self, job_id: str) -> ReconciliationStage:
        aggregate = await self.repository.get_by_id(job_id)
        assert aggregate is not None and aggregate.state is not None
        return aggregate.state.stage


def _run(execution_id: str) -> RunIdentity:
    return RunIdentity(source_instance_id=SOURCE, execution_id=execution_id)


async def _stale_jobs(harness: _Harness) -> list[str]:
    ids = [await harness.request(_run(f"run-{n}")) for n in range(STALE_JOBS)]
    await harness.deliver()
    for job_id in ids:
        await harness.advance_in_store(job_id)
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

    # The projection observes each job's newer step: it is re-armed and completes.
    await harness.deliver()
    progress = [await harness.tick() for _ in range(STALE_JOBS)]
    assert sum(progress) == STALE_JOBS
    assert [await harness.stage_of(job_id) for job_id in ids] == [
        ReconciliationStage.COMPLETED
    ] * STALE_JOBS
    assert len(harness.jobs.published) == STALE_JOBS

    # Terminal events arrive; nothing is left to do and nothing is emitted.
    await harness.deliver()
    events = await harness.events()
    assert [await harness.tick() for _ in range(5)] == [0] * 5
    assert await harness.events() == events


async def test_a_step_waits_for_its_own_event_instead_of_reclaiming_the_stale_row() -> None:
    harness = _Harness()
    job_id = await harness.request(_run("own-event"))
    await harness.deliver()

    assert await harness.tick() == 1  # pending -> publishing, saved to the store
    executed = len(harness.work.executed)
    assert [await harness.tick() for _ in range(5)] == [0] * 5
    assert len(harness.work.executed) == executed  # not re-claimed while unobserved

    await harness.deliver()
    assert await harness.tick() == 1  # publishing -> completed
    assert await harness.stage_of(job_id) is ReconciliationStage.COMPLETED


async def _add_evidence(harness: _Harness, run: RunIdentity) -> None:
    await harness.evidence.append(
        EvidenceBatch(
            batch_id=str(uuid4()), producer_id="producer", evidence=SessionEvidence(run=run)
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
    assert await harness.stage_of(second) is ReconciliationStage.COMPLETED
    latest = await harness.repository.get_by_id(second)
    assert latest is not None and latest.state is not None
    assert latest.state.request.evidence_watermark == 4


async def test_process_pending_logs_wall_time_per_stage(caplog: pytest.LogCaptureFixture) -> None:
    harness = _Harness()
    await _stale_jobs(harness)
    logger = "syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.projection"
    with caplog.at_level(logging.DEBUG, logger=logger):
        await harness.tick()
    stages = [getattr(record, "stage", None) for record in caplog.records]
    assert stages == ["schedule", "execute", "execute"]
    executed = [getattr(record, "job_id", None) for record in caplog.records[1:]]
    assert executed == harness.work.executed
