"""Transfer durable archive objects without making local capture depend on HTTP.

Every capture gets its own exporter outbox (``capture_outboxes``). Handing bytes
to the exporter and sending them both run under the shared deletion fence after
a tombstone check, and a deletion discards the capture's outbox under the
exclusive fence. So after a deletion request commits, withdrawn bytes are never
queued again, never sent, and no earlier queued copy survives.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from apss_session_capture.inventory import QualifiedTranscript

from .capture_delivery_jobs import CaptureDeliveryLeaseLost
from .capture_receipt_evidence import publish_capture_receipt

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import CataloguedCapture
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        SessionEvidenceWritePort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
        SessionTranscriptArchivePort,
    )

    from .capture_deletion_worker import CaptureDeletionWorker
    from .capture_delivery_jobs import CaptureDeliveryLease, PostgresCaptureDeliveryJobs
    from .capture_outboxes import CaptureOutboxPort
    from .deletion_fence import DeletionFence
    from .exporter_transport import CaptureDrain

logger = logging.getLogger(__name__)

_MAX_ENVELOPE = 16 * 1024 * 1024


def _identity(capture: CataloguedCapture) -> QualifiedTranscript:
    if capture.native_id is None:
        raise ValueError("capture has no native identity")
    return QualifiedTranscript(
        source_instance_id=capture.run.source_instance_id,
        harness=capture.harness,
        native_session_id=capture.native_id,
    )


class CaptureDeliveryWorker:
    def __init__(
        self,
        jobs: PostgresCaptureDeliveryJobs,
        archive: SessionTranscriptArchivePort,
        outboxes: CaptureOutboxPort,
        *,
        fence: DeletionFence,
        journal: SessionEvidenceWritePort | None = None,
        deletions: CaptureDeletionWorker | None = None,
        lease_seconds: int = 120,
        retry_seconds: int = 10,
    ) -> None:
        if lease_seconds < 1 or retry_seconds < 0:
            raise ValueError("invalid capture delivery timing")
        self._jobs, self._archive, self._outboxes = jobs, archive, outboxes
        self._lease_seconds, self._retry_seconds = lease_seconds, retry_seconds
        self._journal, self._deletions, self._fence = journal, deletions, fence
        self._retired = False

    async def retire_legacy_outbox(self) -> None:
        """Startup: the shared pre-1398 outbox is never drained again."""
        async with self._fence.exclusive() as conn, conn.transaction():
            await self._jobs.reset_legacy_queue(conn)
        await self._outboxes.retire_legacy()

    async def enqueue_step(self) -> bool:
        if not self._retired:
            await self.retire_legacy_outbox()
            self._retired = True
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
            await self._enqueue(lease)
            await self._jobs.finish(lease, queued=True)
        except Exception:
            logger.warning("Capture delivery enqueue failed; durable acquisition remains retryable")
            with suppress(CaptureDeliveryLeaseLost):
                await self._jobs.finish(lease, queued=False, retry_seconds=self._retry_seconds)
        return True

    async def _enqueue(self, lease: CaptureDeliveryLease) -> None:
        capture = lease.capture
        if capture.content_format != "envelope" or capture.archive.size > _MAX_ENVELOPE:
            raise ValueError("capture is not eligible for envelope delivery")
        identity = _identity(capture)
        outbox = self._outboxes.for_capture(capture.producer_id, capture.capture_id)
        async with self._fence.shared():
            # Inside the fence: a tombstone either exists now (the hash write
            # fails) or cannot commit until these bytes are queued, and then
            # the deletion discards this outbox.
            body = await self._archive.get(capture.archive)
            if body is None:
                raise FileNotFoundError("capture archive is absent")
            await self._jobs.record_content_hash(lease, await outbox.content_hash(body))
            await self._jobs.renew(lease, self._lease_seconds)
            await outbox.enqueue(identity, body)

    async def drain_step(self) -> CaptureDrain | None:
        """Send one capture's outbox, or discard it when the body was withdrawn.

        The shared fence spans the tombstone check and the send. None means
        nothing was sent (idle, or a withdrawn outbox was discarded).
        """
        async with self._fence.shared():
            target = await self._jobs.claim_drain(self._lease_seconds)
            if target is None:
                return None
            if target.withdrawn:
                await self._outboxes.discard(target.producer_id, target.capture_id)
                await self._jobs.finish_drain(target, drained=True)
                return None
            outbox = self._outboxes.for_capture(target.producer_id, target.capture_id)
            try:
                result = await outbox.drain(limit=1)
            except Exception:
                await self._jobs.finish_drain(
                    target, drained=False, retry_seconds=self._retry_seconds
                )
                raise
            await self._jobs.finish_drain(
                target, drained=result.remaining == 0, retry_seconds=self._retry_seconds
            )
            return result

    async def receipt_step(self) -> bool:
        if self._journal is None:
            return False
        lease = await self._jobs.claim_receipt(self._lease_seconds)
        if lease is None:
            return False
        try:
            capture = lease.capture
            if capture.archive.size > _MAX_ENVELOPE:
                raise ValueError("capture is not eligible for receipt lookup")
            outbox = self._outboxes.for_capture(capture.producer_id, capture.capture_id)
            async with self._fence.shared():
                # The lookup hands bytes to the exporter: never after a deletion.
                if await self._jobs.withdrawn(capture):
                    raise PermissionError("capture body was withdrawn")
                body = await self._archive.get(capture.archive)
                if body is None:
                    raise FileNotFoundError("capture archive is absent")
                receipt = await outbox.receipt(_identity(capture), body)
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
