"""Optional replication composition; local capture has no remote prerequisites."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    InventoryReplicationProcessManager,
)

from .capture_delivery_jobs import PostgresCaptureDeliveryJobs
from .capture_delivery_worker import CaptureDeliveryWorker
from .evidence_reader import PostgresSessionEvidence
from .exporter_transport import ExporterCaptureTransport, ExporterConfig, ExporterInventoryTransport
from .replication_jobs import PostgresReplicationJobs
from .replication_supervisor import ReplicationSupervisor
from .replication_worker import InventoryReplicationWorker

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import SessionInventoryReadPort
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
        SessionTranscriptArchivePort,
    )
    from syn_shared.settings.session_inventory import SessionInventorySettings

    from .database import Pool


def create_replication_manager(
    pool: Pool,
    inventory: SessionInventoryReadPort,
    source_id: str,
    settings: SessionInventorySettings,
    *,
    archive: SessionTranscriptArchivePort | None = None,
) -> InventoryReplicationProcessManager | None:
    if not settings.replication_enabled:
        return None
    url, token = settings.replication_store_url, settings.replication_write_token
    if url is None or token is None:
        raise ValueError("inventory replication configuration is incomplete")
    if not settings.exporter_binary.is_file():
        raise ValueError("configured inventory exporter binary does not exist")
    destination = hashlib.sha256(url.rstrip("/").encode()).hexdigest()
    source = hashlib.sha256(source_id.encode()).hexdigest()
    transport = ExporterInventoryTransport(
        ExporterConfig(
            binary=settings.exporter_binary,
            outbox_dir=settings.archive_dir / "replication" / destination / source,
            store_url=url,
            token=token,
        )
    )
    capture_work = None
    if settings.capture_replication_enabled:
        if archive is None or settings.capture_write_token is None:
            raise ValueError("capture delivery requires archive storage and capture credentials")
        capture_work = CaptureDeliveryWorker(
            PostgresCaptureDeliveryJobs(pool, source_id, destination),
            archive,
            ExporterCaptureTransport(
                ExporterConfig(
                    binary=settings.exporter_binary,
                    outbox_dir=settings.archive_dir / "capture-delivery" / destination / source,
                    store_url=url,
                    token=settings.capture_write_token,
                )
            ),
            lease_seconds=settings.lease_seconds,
            retry_seconds=settings.retry_seconds,
            journal=PostgresSessionEvidence(pool),
        )
    supervisor = ReplicationSupervisor(
        InventoryReplicationWorker(
            PostgresReplicationJobs(pool, source_id, destination),
            inventory,
            transport,
            lease_seconds=settings.lease_seconds,
            retry_seconds=settings.retry_seconds,
        ),
        capture_work=capture_work,
    )
    return InventoryReplicationProcessManager(supervisor)
