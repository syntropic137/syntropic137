"""Propagate body tombstones to one replica, reporting done only on acknowledgement.

Deletions travel through their own exporter outbox, separate from uploads. One
deletion is in flight per destination (advisory lane lock), so the exporter's
drain acknowledgement count is attributable to it:

- queued: the exporter holds the delete durably (checkpoint row, not acknowledged)
- propagated: a drain that emptied the deletion outbox acknowledged it remotely
- a delete the exporter dropped without acknowledgement is queued again

The source-content hash comes from the delivery job, recorded before the body
could reach the exporter, so propagation never needs local bytes.

Only owner deletions and retractions propagate (#2107). Automatic local expiry
(age, byte quota) never deletes the replica: the remote copy is what made local
expiry safe. Legacy tombstones recorded before reasons existed default to
``retention_age`` and are therefore never propagated either. An automatic
delete already in flight (queued before this rule) is cancelled, not drained:
its outbox is discarded and its checkpoint removed. An owner request on an
automatically expired object promotes the tombstone, so it then propagates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, get_args

from apss_session_capture.inventory import QualifiedTranscript

from syn_domain.contexts.agent_sessions import OwnerDeletionReason

from .deletion_fence import try_deletion_lane

if TYPE_CHECKING:
    from .database import Connection, Pool
    from .exporter_transport import CaptureDrain, EnqueueReceipt

# Allowlist, so an unknown or future automatic reason is never propagated.
PROPAGATED_REASONS: tuple[str, ...] = get_args(OwnerDeletionReason)


class CaptureDeletionTransport(Protocol):
    async def delete(self, identity: QualifiedTranscript, content_hash: str) -> EnqueueReceipt: ...
    async def drain(self, limit: int = 1) -> CaptureDrain: ...
    async def discard(self) -> None: ...


class CaptureDeletionWorker:
    def __init__(
        self, pool: Pool, transport: CaptureDeletionTransport, source: str, destination: str
    ) -> None:
        self._pool, self._transport = pool, transport
        self._source, self._destination = source, destination

    async def step(self) -> bool:
        async with self._pool.acquire() as conn, conn.transaction():
            if not await try_deletion_lane(conn, self._source, self._destination):
                return False
            if await self._settle_in_flight(conn):
                return True
            return await self._queue_next(conn)

    async def _settle_in_flight(self, conn: Connection) -> bool:
        rows = await conn.fetch(
            """SELECT k.producer_id,k.capture_id,k.acknowledgements::text AS acknowledgements,
            COALESCE(bool_or(d.reason=ANY($3::text[])),FALSE)::text AS owner
            FROM session_capture_deletion_checkpoints k
            LEFT JOIN session_capture_catalog c ON c.source_instance_id=k.source_instance_id
            AND c.producer_id=k.producer_id AND c.capture_id=k.capture_id
            LEFT JOIN session_body_deletions d ON d.source_instance_id=c.source_instance_id
            AND d.archive_sha256=c.payload->'archive'->>'sha256'
            WHERE k.source_instance_id=$1 AND k.destination_id=$2 AND NOT k.acknowledged
            GROUP BY k.producer_id,k.capture_id,k.acknowledgements
            ORDER BY k.producer_id,k.capture_id LIMIT 1""",
            self._source,
            self._destination,
            list(PROPAGATED_REASONS),
        )
        if not rows:
            return False
        row = rows[0]
        args = (self._source, self._destination, row["producer_id"], row["capture_id"])
        where = """WHERE source_instance_id=$1 AND destination_id=$2
            AND producer_id=$3 AND capture_id=$4"""
        if row["owner"] != "true":
            # Automatic expiry queued before #2107: cancel, never drain. The lane
            # holds one delete per destination, so the outbox holds only this one.
            await self._transport.discard()
            await conn.execute(f"DELETE FROM session_capture_deletion_checkpoints {where}", *args)
            return True
        drained = await self._transport.drain(limit=1)
        acknowledgements = int(row["acknowledgements"]) + drained.acknowledged
        if drained.remaining > 0:
            await conn.execute(
                f"UPDATE session_capture_deletion_checkpoints SET acknowledgements=$5 {where}",
                *args,
                acknowledgements,
            )
        elif acknowledgements > 0:
            await conn.execute(
                f"UPDATE session_capture_deletion_checkpoints SET acknowledged=TRUE {where}",
                *args,
            )
        else:
            # Outbox empty with no acknowledgement: never claim propagation.
            await conn.execute(f"DELETE FROM session_capture_deletion_checkpoints {where}", *args)
        return True

    async def _queue_next(self, conn: Connection) -> bool:
        rows = await conn.fetch(
            """SELECT c.producer_id,c.capture_id,c.payload->>'harness' AS harness,
            c.payload->>'native_id' AS native_id,
            COALESCE(j.content_hash,d.content_hash) AS content_hash
            FROM session_body_deletions d JOIN session_capture_catalog c
            ON c.source_instance_id=d.source_instance_id
            AND c.payload->'archive'->>'sha256'=d.archive_sha256
            JOIN session_capture_delivery_jobs j ON j.source_instance_id=c.source_instance_id
            AND j.producer_id=c.producer_id AND j.capture_id=c.capture_id AND j.destination_id=$2
            WHERE d.source_instance_id=$1 AND c.payload->>'native_id' IS NOT NULL
            AND c.payload->>'content_format'='envelope'
            AND (j.queued OR j.content_hash IS NOT NULL)
            AND COALESCE(j.content_hash,d.content_hash) IS NOT NULL
            AND d.reason=ANY($3::text[])
            AND NOT EXISTS(SELECT 1 FROM session_capture_deletion_checkpoints k
                WHERE k.source_instance_id=c.source_instance_id AND k.destination_id=$2
                AND k.producer_id=c.producer_id AND k.capture_id=c.capture_id)
            ORDER BY d.requested_at,c.producer_id,c.capture_id LIMIT 1""",
            self._source,
            self._destination,
            list(PROPAGATED_REASONS),
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
            (source_instance_id,destination_id,producer_id,capture_id,content_hash)
            VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING""",
            self._source,
            self._destination,
            row["producer_id"],
            row["capture_id"],
            row["content_hash"],
        )
        await conn.execute(
            """UPDATE session_body_deletions d SET content_hash=$3
            WHERE d.source_instance_id=$1 AND d.content_hash IS NULL AND d.archive_sha256=(
                SELECT c.payload->'archive'->>'sha256' FROM session_capture_catalog c
                WHERE c.source_instance_id=$1 AND c.producer_id=$2 AND c.capture_id=$4)""",
            self._source,
            row["producer_id"],
            row["content_hash"],
            row["capture_id"],
        )
        return True
