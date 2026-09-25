"""Compose durable inventory adapters and domain handlers without remote dependencies."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from event_sourcing import RepositoryFactory

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.agent_sessions import (
    BackfillSessionInventoryHandler,
    BuildInventorySnapshotHandler,
    CaptureLocalTranscriptHandler,
    HostSessionEvidenceProjector,
    InventoryJobLease,
    InventoryReconciliationAggregate,
    InventoryReconciliationProcessManager,
    InventoryStepHandler,
    ProcessHistoryBackfillQueueHandler,
    ReadLocalTranscriptHandler,
    RefreshSessionInventoryHandler,
    SchedulePendingInventoryHandler,
)

from .body_availability import PostgresBodyAvailability
from .body_retention import LocalBodyRetention
from .capture_catalog import PostgresCaptureCatalog
from .child_journal import ChildJournalDrain
from .clock import InventoryRecoveryClock
from .deletion_fence import DeletionFence
from .docker_recovery import DockerSpoolRecovery
from .evidence_reader import PostgresSessionEvidence
from .history_receipts import PostgresBackfillReceipts, PostgresHistoryBackfillQueue
from .history_source import PostgresHistoricalEvidenceSource
from .installation_identity import installation_identity
from .local_archive import LocalSessionTranscriptArchive
from .native_evidence import AgenticNativeSessionEvidence
from .postgres_inventory import PostgresSessionInventory
from .postgres_jobs import PostgresSessionInventoryJobs
from .postgres_settlements import PostgresSettlementDeadlines
from .postgres_spools import PostgresCaptureSpools
from .recovery_worker import CaptureRecoveryWorker
from .replication_runtime import (
    capture_destination_id,
    capture_outboxes,
    create_replication_manager,
)
from .spool_drain import LocalSpoolDrain
from .spool_release import CaptureSpoolRetention
from .transcript_access import InstallationTranscriptAccess
from .transcript_deletions import PostgresTranscriptDeletions

if TYPE_CHECKING:
    from event_sourcing import EventStoreClient

    from syn_domain.contexts.agent_sessions.slices.replicate_session_inventory.projection import (
        InventoryReplicationProcessManager,
    )
    from syn_shared.settings.session_inventory import SessionInventorySettings

    from .database import Pool
    from .history_source import CaptureObservationQuery


logger = logging.getLogger(__name__)

#: Historical acquisition bounds per execution. Exceeding one fails the backfill
#: visibly; a truncated history is never journaled as if it were complete.
HISTORY_MAX_OBSERVATIONS = 10_000
HISTORY_MAX_ARCHIVES = 2_000
HISTORY_MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class InventoryRuntime:
    source_instance_id: str
    evidence: PostgresSessionEvidence
    inventory: PostgresSessionInventory
    jobs: PostgresSessionInventoryJobs
    archive: LocalSessionTranscriptArchive
    body_availability: PostgresBodyAvailability
    transcripts: ReadLocalTranscriptHandler
    repository: RepositoryAdapter[InventoryReconciliationAggregate]
    processor: InventoryReconciliationProcessManager
    clock: InventoryRecoveryClock
    capture: CaptureLocalTranscriptHandler
    drain: LocalSpoolDrain
    spools: PostgresCaptureSpools
    history_queue: PostgresHistoryBackfillQueue
    catalog: PostgresCaptureCatalog
    access: InstallationTranscriptAccess
    deletions: PostgresTranscriptDeletions
    fence: DeletionFence
    replication: InventoryReplicationProcessManager | None = None
    history: BackfillSessionInventoryHandler | None = None
    """None when no observability reader is wired; explicit backfill is then unavailable."""


@dataclass(frozen=True)
class InventoryWork:
    scheduler: SchedulePendingInventoryHandler
    step: InventoryStepHandler
    recovery: CaptureRecoveryWorker | None = None
    retention: LocalBodyRetention | None = None
    history: ProcessHistoryBackfillQueueHandler | None = None
    spool_release: CaptureSpoolRetention | None = None

    async def schedule(self) -> None:
        if self.retention is not None:
            try:
                await self.retention.drain()
            except Exception as exc:
                # Type only: messages can name archive paths or exporter output.
                logger.error(
                    "Local body deletion failed (%s); durable request remains pending",
                    type(exc).__name__,
                )
        if self.spool_release is not None:
            try:
                await self.spool_release.step()
            except Exception as exc:
                logger.error(
                    "Capture spool release failed (%s); durable intent remains pending",
                    type(exc).__name__,
                )
        if self.recovery is not None:
            await self.recovery.step()
        if self.history is not None:
            try:
                await self.history.handle()
            except Exception:
                logger.exception("History backfill tick failed; durable queue remains pending")
        # Same tick: journaled history wakes the ordinary reconciliation outbox.
        await self.scheduler.handle()

    async def execute(self, lease: InventoryJobLease) -> None:
        await self.step.handle(lease)


async def create_inventory_runtime(
    pool: Pool,
    event_store: EventStoreClient,
    settings: SessionInventorySettings,
    *,
    recovery_image: str | None = None,
    observations: CaptureObservationQuery | None = None,
) -> InventoryRuntime:
    evidence = PostgresSessionEvidence(pool)
    inventory = PostgresSessionInventory(pool)
    jobs = PostgresSessionInventoryJobs(pool)
    # One schema bootstrap initializes the shared durable tables.
    await evidence.ensure_ready()
    archive = LocalSessionTranscriptArchive(settings.archive_dir)
    await archive.ensure_ready()
    source_id = await asyncio.to_thread(
        installation_identity, settings.archive_dir, settings.source_instance_id
    )
    spools = PostgresCaptureSpools(pool, source_id)
    receipts = PostgresBackfillReceipts(pool)
    await receipts.ensure_ready()
    history_queue = PostgresHistoryBackfillQueue(pool, source_id)
    sdk_repo = RepositoryFactory(event_store).create_repository(
        InventoryReconciliationAggregate,  # type: ignore[arg-type]  # ESP SDK event generic is invariant
        aggregate_type="InventoryReconciliation",
    )
    repository = RepositoryAdapter(sdk_repo)
    builder = BuildInventorySnapshotHandler(
        evidence,
        inventory,
        max_evidence_records=settings.max_evidence_records,
        max_evidence_batches=settings.max_evidence_batches,
    )
    capture = CaptureLocalTranscriptHandler(
        archive, evidence, AgenticNativeSessionEvidence(), catalog=PostgresCaptureCatalog(pool)
    )
    drain = LocalSpoolDrain(capture)
    recovery = DockerSpoolRecovery(recovery_image) if recovery_image is not None else None
    spool_release = (
        CaptureSpoolRetention(
            pool,
            source_id,
            recovery,
            evidence,
            age_seconds=settings.spool_retention_seconds,
            max_bytes=settings.spool_max_bytes,
        )
        if recovery is not None
        else None
    )
    catalog = PostgresCaptureCatalog(pool)
    access = InstallationTranscriptAccess(pool, source_id)
    fence = DeletionFence(pool, source_id)
    history = (
        BackfillSessionInventoryHandler(
            PostgresHistoricalEvidenceSource(
                pool,
                observations,
                archive,
                AgenticNativeSessionEvidence(),
                max_observations=HISTORY_MAX_OBSERVATIONS,
                max_archives=HISTORY_MAX_ARCHIVES,
            ),
            receipts,
            evidence,
            RefreshSessionInventoryHandler(repository, evidence, inventory),
        )
        if observations is not None
        else None
    )
    work = InventoryWork(
        history=ProcessHistoryBackfillQueueHandler(
            history_queue,
            history,
            lease_seconds=settings.lease_seconds,
            retry_seconds=settings.retry_seconds,
            max_items_per_tick=settings.max_jobs_per_tick,
            max_attempts=HISTORY_MAX_ATTEMPTS,
        )
        if history is not None
        else None,
        # Always present: owner deletions run even without automatic retention.
        retention=LocalBodyRetention(
            pool,
            archive,
            source_id,
            age_seconds=settings.local_body_retention_seconds,
            max_bytes=settings.local_body_max_bytes,
            exporter_binary=settings.exporter_binary,
        ),
        spool_release=spool_release,
        recovery=CaptureRecoveryWorker(
            spools,
            recovery,
            drain,
            lease_seconds=settings.lease_seconds,
            retry_seconds=settings.retry_seconds,
            children=ChildJournalDrain(evidence),
            release=spool_release,
        )
        if recovery is not None
        else None,
        scheduler=SchedulePendingInventoryHandler(evidence, inventory, repository),
        step=InventoryStepHandler(
            repository, jobs, builder, evidence, lease_seconds=settings.lease_seconds
        ),
    )
    return InventoryRuntime(
        source_instance_id=source_id,
        replication=create_replication_manager(
            pool, inventory, source_id, settings, archive=archive
        ),
        capture=capture,
        drain=drain,
        spools=spools,
        history=history,
        history_queue=history_queue,
        evidence=evidence,
        inventory=inventory,
        jobs=jobs,
        archive=archive,
        body_availability=PostgresBodyAvailability(pool),
        transcripts=ReadLocalTranscriptHandler(catalog, archive, access),
        catalog=catalog,
        access=access,
        deletions=PostgresTranscriptDeletions(
            pool,
            source_id,
            capture_destination_id(settings),
            archive=archive,
            fence=fence,
            outboxes=capture_outboxes(settings, source_id),
        ),
        fence=fence,
        repository=repository,
        processor=InventoryReconciliationProcessManager(
            jobs,
            work,
            lease_seconds=settings.lease_seconds,
            retry_seconds=settings.retry_seconds,
            max_jobs_per_tick=settings.max_jobs_per_tick,
            host_evidence=HostSessionEvidenceProjector(
                evidence,
                source_id,
                spools,
                settlements=PostgresSettlementDeadlines(pool, source_id),
                settlement_grace=timedelta(seconds=settings.settlement_grace_seconds),
            ),
        ),
        clock=InventoryRecoveryClock(event_store, interval_seconds=settings.sweep_interval_seconds),
    )
