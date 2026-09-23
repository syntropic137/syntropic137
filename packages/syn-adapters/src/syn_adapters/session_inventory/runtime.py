"""Compose durable inventory adapters and domain handlers without remote dependencies."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from event_sourcing import RepositoryFactory

from syn_adapters.storage.repositories import RepositoryAdapter
from syn_domain.contexts.agent_sessions import (
    BuildInventorySnapshotHandler,
    CaptureLocalTranscriptHandler,
    HostSessionEvidenceProjector,
    InventoryJobLease,
    InventoryReconciliationAggregate,
    InventoryReconciliationProcessManager,
    InventoryStepHandler,
    ReadLocalTranscriptHandler,
    SchedulePendingInventoryHandler,
)

from .body_retention import LocalBodyRetention
from .capture_catalog import PostgresCaptureCatalog
from .child_journal import ChildJournalDrain
from .clock import InventoryRecoveryClock
from .docker_recovery import DockerSpoolRecovery
from .evidence_reader import PostgresSessionEvidence
from .installation_identity import installation_identity
from .local_archive import LocalSessionTranscriptArchive
from .native_evidence import AgenticNativeSessionEvidence
from .postgres_inventory import PostgresSessionInventory
from .postgres_jobs import PostgresSessionInventoryJobs
from .postgres_spools import PostgresCaptureSpools
from .recovery_worker import CaptureRecoveryWorker
from .replication_runtime import create_replication_manager
from .spool_drain import LocalSpoolDrain
from .transcript_access import InstallationTranscriptAccess

if TYPE_CHECKING:
    from event_sourcing import EventStoreClient

    from syn_domain.contexts.agent_sessions.slices.replicate_session_inventory.projection import (
        InventoryReplicationProcessManager,
    )
    from syn_shared.settings.session_inventory import SessionInventorySettings

    from .database import Pool


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InventoryRuntime:
    source_instance_id: str
    evidence: PostgresSessionEvidence
    inventory: PostgresSessionInventory
    jobs: PostgresSessionInventoryJobs
    archive: LocalSessionTranscriptArchive
    transcripts: ReadLocalTranscriptHandler
    repository: RepositoryAdapter[InventoryReconciliationAggregate]
    processor: InventoryReconciliationProcessManager
    clock: InventoryRecoveryClock
    capture: CaptureLocalTranscriptHandler
    drain: LocalSpoolDrain
    spools: PostgresCaptureSpools
    replication: InventoryReplicationProcessManager | None = None


@dataclass(frozen=True)
class _InventoryWork:
    scheduler: SchedulePendingInventoryHandler
    step: InventoryStepHandler
    recovery: CaptureRecoveryWorker | None = None
    retention: LocalBodyRetention | None = None

    async def schedule(self) -> None:
        if self.retention is not None:
            try:
                await self.retention.step()
            except Exception:
                logger.exception("Local body expiry failed; durable deletion remains pending")
        if self.recovery is not None:
            await self.recovery.step()
        await self.scheduler.handle()

    async def execute(self, lease: InventoryJobLease) -> None:
        await self.step.handle(lease)


async def create_inventory_runtime(
    pool: Pool,
    event_store: EventStoreClient,
    settings: SessionInventorySettings,
    *,
    recovery_image: str | None = None,
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
    work = _InventoryWork(
        retention=LocalBodyRetention(
            pool, archive, source_id, age_seconds=settings.local_body_retention_seconds
        )
        if settings.local_body_retention_seconds is not None
        else None,
        recovery=CaptureRecoveryWorker(
            spools,
            DockerSpoolRecovery(recovery_image),
            drain,
            lease_seconds=settings.lease_seconds,
            retry_seconds=settings.retry_seconds,
            children=ChildJournalDrain(evidence),
        )
        if recovery_image is not None
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
        evidence=evidence,
        inventory=inventory,
        jobs=jobs,
        archive=archive,
        transcripts=ReadLocalTranscriptHandler(
            PostgresCaptureCatalog(pool), archive, InstallationTranscriptAccess(pool, source_id)
        ),
        repository=repository,
        processor=InventoryReconciliationProcessManager(
            jobs,
            work,
            lease_seconds=settings.lease_seconds,
            retry_seconds=settings.retry_seconds,
            max_jobs_per_tick=settings.max_jobs_per_tick,
            host_evidence=HostSessionEvidenceProjector(evidence, source_id, spools),
        ),
        clock=InventoryRecoveryClock(event_store, interval_seconds=settings.sweep_interval_seconds),
    )
