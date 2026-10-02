"""Optional replication composition; local capture has no remote prerequisites."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    InventoryReplicationProcessManager,
)

from .capture_deletion_worker import CaptureDeletionWorker
from .capture_delivery_jobs import PostgresCaptureDeliveryJobs
from .capture_delivery_worker import CaptureDeliveryWorker
from .capture_outboxes import ExporterCaptureOutboxes
from .deletion_fence import DeletionFence
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


def replication_destination_id(url: str) -> str:
    """Opaque server-derived destination identity; never the caller-visible URL."""
    return hashlib.sha256(url.rstrip("/").encode()).hexdigest()


def capture_destination_id(settings: SessionInventorySettings) -> str | None:
    """Destination that receives body deletions, or None when capture delivery is off."""
    url = settings.replication_store_url
    if not (settings.replication_enabled and settings.capture_replication_enabled) or url is None:
        return None
    return replication_destination_id(url)


def capture_outboxes(
    settings: SessionInventorySettings, source_id: str
) -> ExporterCaptureOutboxes | None:
    """Per-capture upload outboxes, or None when capture delivery is off."""
    destination = capture_destination_id(settings)
    url, token = settings.replication_store_url, settings.capture_write_token
    if destination is None or url is None or token is None:
        return None
    source = hashlib.sha256(source_id.encode()).hexdigest()
    return ExporterCaptureOutboxes(
        binary=settings.exporter_binary,
        root=settings.archive_dir / "capture-uploads" / destination / source,
        legacy_root=settings.archive_dir / "capture-delivery" / destination / source,
        store_url=url,
        token=token,
    )


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
    destination = replication_destination_id(url)
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
        outboxes = capture_outboxes(settings, source_id)
        if outboxes is None:
            raise ValueError("capture delivery configuration is incomplete")
        deletion_transport = ExporterCaptureTransport(
            ExporterConfig(
                binary=settings.exporter_binary,
                # Deletes never queue behind uploads: their outbox is separate.
                outbox_dir=settings.archive_dir / "capture-deletions" / destination / source,
                store_url=url,
                token=settings.capture_write_token,
            )
        )
        capture_work = CaptureDeliveryWorker(
            PostgresCaptureDeliveryJobs(pool, source_id, destination),
            archive,
            outboxes,
            lease_seconds=settings.lease_seconds,
            retry_seconds=settings.retry_seconds,
            journal=PostgresSessionEvidence(pool),
            deletions=CaptureDeletionWorker(pool, deletion_transport, source_id, destination),
            fence=DeletionFence(pool, source_id),
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
