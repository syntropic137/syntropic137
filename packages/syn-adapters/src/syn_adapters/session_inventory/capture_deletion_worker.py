"""Checkpoint deletion only after the exporter's local outbox is durable."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apss_session_capture.inventory import QualifiedTranscript

if TYPE_CHECKING:
    from .database import Pool
    from .exporter_transport import ExporterCaptureTransport


class CaptureDeletionWorker:
    def __init__(
        self, pool: Pool, transport: ExporterCaptureTransport, source: str, destination: str
    ) -> None:
        self._pool, self._transport = pool, transport
        self._source, self._destination = source, destination

    async def step(self) -> bool:
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """SELECT c.producer_id,c.capture_id,c.payload->>'harness' AS harness,
                c.payload->>'native_id' AS native_id,d.content_hash
                FROM session_body_deletions d JOIN session_capture_catalog c
                ON c.source_instance_id=d.source_instance_id
                AND c.payload->'archive'->>'sha256'=d.archive_sha256
                WHERE d.source_instance_id=$1 AND d.content_hash IS NOT NULL
                AND c.payload->>'native_id' IS NOT NULL
                AND c.payload->>'content_format'='envelope'
                AND NOT EXISTS(SELECT 1 FROM session_capture_deletion_checkpoints k
                    WHERE k.source_instance_id=c.source_instance_id AND k.destination_id=$2
                    AND k.producer_id=c.producer_id AND k.capture_id=c.capture_id)
                ORDER BY d.requested_at,c.producer_id,c.capture_id
                FOR UPDATE OF d SKIP LOCKED LIMIT 1""",
                self._source,
                self._destination,
            )
            if not rows:
                return False
            row = rows[0]
            await self._transport.delete(
                QualifiedTranscript(
                    source_instance_id=self._source,
                    harness=row["harness"],
                    native_session_id=row["native_id"],
                ),
                row["content_hash"],
            )
            await conn.execute(
                """INSERT INTO session_capture_deletion_checkpoints
                (source_instance_id,destination_id,producer_id,capture_id)
                VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING""",
                self._source,
                self._destination,
                row["producer_id"],
                row["capture_id"],
            )
        return True
