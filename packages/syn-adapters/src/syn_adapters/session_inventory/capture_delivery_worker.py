"""Transfer durable archive objects without making local capture depend on HTTP."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from apss_session_capture.inventory import QualifiedTranscript

from .capture_delivery_jobs import CaptureDeliveryLeaseLost
from .capture_receipt_evidence import publish_capture_receipt

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        SessionEvidenceWritePort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
        SessionTranscriptArchivePort,
    )

    from .capture_deletion_worker import CaptureDeletionWorker
    from .capture_delivery_jobs import PostgresCaptureDeliveryJobs
    from .deletion_fence import DeletionFence
    from .exporter_transport import CaptureDrain, ExporterCaptureTransport

logger = logging.getLogger(__name__)


class CaptureDeliveryWorker:
    def __init__(
        self,
        jobs: PostgresCaptureDeliveryJobs,
        archive: SessionTranscriptArchivePort,
        transport: ExporterCaptureTransport,
        *,
        journal: SessionEvidenceWritePort | None = None,
        deletions: CaptureDeletionWorker | None = None,
        fence: DeletionFence | None = None,
        lease_seconds: int = 120,
        retry_seconds: int = 10,
    ) -> None:
        if lease_seconds < 1 or retry_seconds < 0:
            raise ValueError("invalid capture delivery timing")
        self._jobs, self._archive, self._transport = jobs, archive, transport
        self._lease_seconds, self._retry_seconds = lease_seconds, retry_seconds
        self._journal = journal
        self._deletions = deletions
        self._fence = fence

    async def enqueue_step(self) -> bool:
        if self._deletions is not None:
            # Deletion progress never waits behind, or blocks, ordinary uploads.
            try:
                await self._deletions.step()
            except Exception as exc:
                logger.warning(
                    "Replica deletion step failed (%s); durable work will retry",
                    type(exc).__name__,
                )
        # Each live tick checks one durable acknowledgement and queues at most
        # one capture. HTTP delivery remains in the independently scheduled drain.
        if self._journal is not None:
            await self.receipt_step()
        await self._jobs.discover()
        lease = await self._jobs.claim(self._lease_seconds)
        if lease is None:
            return False
        try:
            capture = lease.capture
            if (
                capture.content_format != "envelope"
                or capture.native_id is None
                or capture.archive.size > 16 * 1024 * 1024
            ):
                raise ValueError("capture is not eligible for envelope delivery")
            body = await self._archive.get(capture.archive)
            if body is None:
                raise FileNotFoundError("capture archive is absent")
            # Durable before the exporter can hold the bytes: deletion must not
            # depend on this local body surviving.
            await self._jobs.record_content_hash(lease, await self._transport.content_hash(body))
            await self._jobs.renew(lease, self._lease_seconds)
            await self._transport.enqueue(
                QualifiedTranscript(
                    source_instance_id=capture.run.source_instance_id,
                    harness=capture.harness,
                    native_session_id=capture.native_id,
                ),
                body,
            )
            await self._jobs.finish(lease, queued=True)
        except Exception:
            logger.warning("Capture delivery enqueue failed; durable acquisition remains retryable")
            with suppress(CaptureDeliveryLeaseLost):
                await self._jobs.finish(lease, queued=False, retry_seconds=self._retry_seconds)
        return True

    async def drain_step(self) -> CaptureDrain | None:
        """Send queued uploads only while no tombstoned body can be among them.

        The shared fence spans the check and the send, so a deletion request
        either waits for this drain or is seen by it. None means fenced.
        """
        if self._fence is None:
            raise RuntimeError("capture delivery requires the deletion fence")
        async with self._fence.shared() as conn:
            if await self._jobs.drain_blocked(conn):
                logger.info("Capture delivery paused until replica deletions are acknowledged")
                return None
            return await self._transport.drain(limit=1)

    async def receipt_step(self) -> bool:
        if self._journal is None:
            return False
        lease = await self._jobs.claim_receipt(self._lease_seconds)
        if lease is None:
            return False
        try:
            capture = lease.capture
            if capture.native_id is None or capture.archive.size > 16 * 1024 * 1024:
                raise ValueError("capture is not eligible for receipt lookup")
            body = await self._archive.get(capture.archive)
            if body is None:
                raise FileNotFoundError("capture archive is absent")
            receipt = await self._transport.receipt(
                QualifiedTranscript(
                    source_instance_id=capture.run.source_instance_id,
                    harness=capture.harness,
                    native_session_id=capture.native_id,
                ),
                body,
            )
            if receipt is not None:
                await publish_capture_receipt(self._journal, capture, lease.destination_id, receipt)
            # Append before checkpoint: interrupted publication repeats the same
            # immutable batch, including when another worker takes over the lease.
            await self._jobs.finish_receipt(
                lease, recorded=receipt is not None, retry_seconds=self._retry_seconds
            )
        except Exception:
            logger.warning("Capture receipt publication failed; durable work will retry")
            with suppress(CaptureDeliveryLeaseLost):
                await self._jobs.finish_receipt(
                    lease, recorded=False, retry_seconds=self._retry_seconds
                )
        return True
