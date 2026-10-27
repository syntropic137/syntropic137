"""Bounded, restart-safe local body expiry; discovery history is retained."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import ArchivedTranscript
from syn_domain.contexts.agent_sessions.ports.SessionArchiveSinkPort import UploadedRevision

from .deletion_fence import lock_tombstones_xact
from .exporter_transport import original_envelope_hash

if TYPE_CHECKING:
    from pathlib import Path

    from .database import Connection, Pool
    from .expiry_gate import ConfirmedExpiryGate
    from .local_archive import LocalSessionTranscriptArchive

AUTOMATIC_REASONS = ("retention_age", "retention_quota")

# A body backs an uploaded revision only when its capture's delivery to this
# destination was acknowledged remotely (a recorded receipt), with the content
# hash persisted before upload. The gate still confirms right before deleting.
_UPLOADED = """COALESCE(j.queued AND j.receipt_recorded AND NOT j.cancelled
    AND j.content_hash IS NOT NULL AND u.payload->>'native_id' IS NOT NULL, FALSE)"""
_BACKING = """FROM session_capture_catalog u
    LEFT JOIN session_capture_delivery_jobs j ON j.destination_id=$DEST
    AND j.source_instance_id=u.source_instance_id AND j.producer_id=u.producer_id
    AND j.capture_id=u.capture_id
    WHERE u.source_instance_id=$1 AND u.payload->'archive'->>'sha256'=$SHA"""


class LocalBodyRetention:
    """Live-only cleanup owner for local transcript bodies.

    Deletion requests come from three sources, all recorded as durable SQL
    tombstones before any byte is removed: age expiry, the archive byte quota,
    and owner deletion/retraction through the API. ``step`` executes exactly one
    pending request whatever its source, so owner deletions run even when no
    automatic retention is configured.

    With a ``gate`` (#2107, off by default), automatic expiry never deletes
    bytes the remote archive has not confirmed: discovery only tombstones bodies
    whose every capture was uploaded, and the gate confirms each uploaded
    revision immediately before deletion. A held expiry withdraws its own
    tombstone and is not rediscovered until ``hold_seconds`` pass. Owner
    deletions and retractions are never gated.
    """

    def __init__(
        self,
        pool: Pool,
        archive: LocalSessionTranscriptArchive,
        source: str,
        *,
        age_seconds: int | None = None,
        max_bytes: int | None = None,
        exporter_binary: Path | None = None,
        gate: ConfirmedExpiryGate | None = None,
        destination_id: str | None = None,
        hold_seconds: int = 3600,
    ) -> None:
        if not source.strip():
            raise ValueError("body retention requires an installation identity")
        if (age_seconds is not None and age_seconds < 1) or (
            max_bytes is not None and max_bytes < 1
        ):
            raise ValueError("body retention quotas must be positive when configured")
        self._pool, self._archive, self._source = pool, archive, source
        self._age = age_seconds
        self._max_bytes = max_bytes
        self._exporter = exporter_binary
        if gate is not None and not (destination_id and destination_id.strip()):
            raise ValueError("gated body expiry requires the capture destination")
        if hold_seconds < 1:
            raise ValueError("expiry hold must be positive")
        self._gate, self._destination, self._hold = gate, destination_id, hold_seconds

    def _gated(self) -> str:
        """Discovery filter under the gate; the destination is bound as ``$4``."""
        if self._gate is None:
            return ""
        backing = _BACKING.replace("$DEST", "$4").replace("$SHA", "sha")
        return f"""AND NOT EXISTS(SELECT 1 FROM session_body_retention_holds h
                WHERE h.source_instance_id=$1 AND h.archive_sha256=sha AND h.held_until>now())
            AND NOT EXISTS(SELECT 1 {backing} AND NOT {_UPLOADED})"""

    def _gated_args(self) -> tuple[str, ...]:
        return () if self._gate is None or self._destination is None else (self._destination,)

    async def discover(self, limit: int = 100) -> None:
        if not 1 <= limit <= 500:
            raise ValueError("retention discovery limit must be 1..500")
        if self._age is not None:
            await self._discover_age(limit)
        if self._max_bytes is not None:
            await self._discover_quota(limit)

    async def _discover_age(self, limit: int) -> None:
        """Tombstone objects whose every referencing capture is past the age.

        Bodies are content-addressed, so one object can back captures acquired
        at very different times. Judging it by its oldest capture would erase
        bytes a recent capture still references; an object expires only when
        its newest referencing capture has aged out.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await lock_tombstones_xact(conn, self._source)
            await conn.execute(
                """WITH objects AS (
                    SELECT c.payload->'archive'->>'sha256' AS sha,
                    min((c.payload->'archive')::text) AS archive,
                    max(c.created_at) AS last_seen
                    FROM session_capture_catalog c
                    WHERE c.source_instance_id=$1
                    AND NOT EXISTS(SELECT 1 FROM session_body_deletions d
                        WHERE d.source_instance_id=c.source_instance_id
                        AND d.archive_sha256=c.payload->'archive'->>'sha256')
                    GROUP BY 1
                    HAVING max(c.created_at)<=now()-$2::double precision*interval '1 second'
                )
                INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive,reason)
                SELECT $1,sha,archive::jsonb,'retention_age' FROM objects
                WHERE TRUE """
                + self._gated()
                + """
                ORDER BY last_seen,sha LIMIT $3
                ON CONFLICT DO NOTHING""",
                self._source,
                self._age,
                limit,
                *self._gated_args(),
            )

    async def _discover_quota(self, limit: int) -> None:
        """Keep the most recently referenced objects within the byte quota.

        Size counts each exact object once however many captures share it, and
        an object is as recent as its newest referencing capture: the objects
        whose newest reference is oldest are evicted first. Objects already
        tombstoned no longer count against the quota.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await lock_tombstones_xact(conn, self._source)
            await conn.execute(
                """WITH objects AS (
                    SELECT c.payload->'archive'->>'sha256' AS sha,
                    min((c.payload->'archive')::text) AS archive,
                    max((c.payload->'archive'->>'size')::bigint) AS size,
                    max(c.created_at) AS last_seen
                    FROM session_capture_catalog c
                    WHERE c.source_instance_id=$1
                    AND NOT EXISTS(SELECT 1 FROM session_body_deletions d
                        WHERE d.source_instance_id=c.source_instance_id
                        AND d.archive_sha256=c.payload->'archive'->>'sha256')
                    GROUP BY 1
                ), ranked AS (
                    SELECT sha,archive,last_seen,
                    sum(size) OVER (ORDER BY last_seen DESC,sha DESC) AS newer_total
                    FROM objects
                )
                INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive,reason)
                SELECT $1,sha,archive::jsonb,'retention_quota' FROM ranked
                WHERE newer_total>$2 """
                + self._gated()
                + """
                ORDER BY last_seen,sha LIMIT $3
                ON CONFLICT DO NOTHING""",
                self._source,
                self._max_bytes,
                limit,
                *self._gated_args(),
            )

    async def drain(self, max_steps: int = 20) -> int:
        """Execute up to ``max_steps`` pending deletions; stop early when idle."""
        if not 1 <= max_steps <= 500:
            raise ValueError("retention step bound must be 1..500")
        await self.discover()
        done = 0
        while done < max_steps and await self._execute_one():
            done += 1
        return done

    async def step(self) -> bool:
        await self.discover()
        return await self._execute_one()

    async def _execute_one(self) -> bool:
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """SELECT d.archive::text,
                COALESCE(d.content_hash,(SELECT j.content_hash
                    FROM session_capture_delivery_jobs j JOIN session_capture_catalog c
                    USING(source_instance_id,producer_id,capture_id)
                    WHERE c.source_instance_id=d.source_instance_id
                    AND c.payload->'archive'->>'sha256'=d.archive_sha256
                    AND j.content_hash IS NOT NULL LIMIT 1)) AS content_hash,
                (EXISTS(SELECT 1 FROM session_capture_delivery_jobs j
                    JOIN session_capture_catalog c USING(source_instance_id,producer_id,capture_id)
                    WHERE c.source_instance_id=d.source_instance_id
                    AND c.payload->'archive'->>'sha256'=d.archive_sha256
                    AND j.queued AND j.content_hash IS NULL))::text AS legacy,
                d.reason
                FROM session_body_deletions d
                WHERE source_instance_id=$1 AND deleted_at IS NULL
                ORDER BY requested_at,archive_sha256 FOR UPDATE SKIP LOCKED LIMIT 1""",
                self._source,
            )
            if not rows:
                return False
            archive = ArchivedTranscript.model_validate_json(rows[0]["archive"])
            if rows[0]["reason"] in AUTOMATIC_REASONS and not await self._confirmed(conn, archive):
                return True
            content_hash = rows[0]["content_hash"]
            if content_hash is None and rows[0]["legacy"] == "true":
                # Deliveries queued before content hashes were recorded at enqueue
                # time: derive the replica deletion key while bytes still exist.
                body = await self._archive.get(archive)
                if body is not None:
                    if self._exporter is None:
                        raise RuntimeError("Legacy envelope expiry requires the standard exporter")
                    content_hash = await original_envelope_hash(self._exporter, body)
                # Absent bytes cannot be hashed; the replica state reports it
                # as unresolvable instead of blocking erasure forever.
            if content_hash is not None:
                await conn.execute(
                    """UPDATE session_body_deletions SET content_hash=$3
                    WHERE source_instance_id=$1 AND archive_sha256=$2 AND content_hash IS NULL""",
                    self._source,
                    archive.sha256,
                    content_hash,
                )
            # Filesystem tombstone precedes SQL acknowledgement. On rollback or
            # process death the next worker repeats this idempotent operation.
            await self._archive.delete(archive)
            await conn.execute(
                """UPDATE session_capture_delivery_jobs j SET cancelled=TRUE
                FROM session_capture_catalog c
                WHERE j.source_instance_id=c.source_instance_id
                AND j.producer_id=c.producer_id AND j.capture_id=c.capture_id
                AND c.source_instance_id=$1 AND c.payload->'archive'->>'sha256'=$2""",
                self._source,
                archive.sha256,
            )
            await conn.execute(
                """UPDATE session_body_deletions SET deleted_at=now()
                WHERE source_instance_id=$1 AND archive_sha256=$2""",
                self._source,
                archive.sha256,
            )
        return True

    async def _confirmed(self, conn: Connection, archive: ArchivedTranscript) -> bool:
        """Gate one automatic expiry; on a hold, withdraw it and keep the bytes."""
        if self._gate is None or self._destination is None:
            return True
        backing = _BACKING.replace("$DEST", "$3").replace("$SHA", "$2")
        rows = await conn.fetch(
            f"""SELECT u.payload->>'harness' AS harness, u.payload->>'native_id' AS native_id,
            j.content_hash, ({_UPLOADED})::text AS uploaded {backing}""",
            self._source,
            archive.sha256,
            self._destination,
        )
        # One revision per qualified identity and hash: several runs can hold
        # the same transcript bytes, and the archive stores them once.
        uploaded = sorted(
            {
                (row["harness"], row["native_id"], row["content_hash"])
                for row in rows
                if row["uploaded"] == "true"
            }
        )
        decision = await self._gate.decide(
            [
                UploadedRevision(
                    source_instance_id=self._source,
                    harness=harness,
                    native_session_id=native_id,
                    content_hash=content_hash,
                )
                for harness, native_id, content_hash in uploaded
            ],
            all_uploaded=bool(rows) and all(row["uploaded"] == "true" for row in rows),
        )
        if decision.hold is None:
            return True
        await conn.execute(
            """DELETE FROM session_body_deletions WHERE source_instance_id=$1
            AND archive_sha256=$2 AND deleted_at IS NULL AND reason=ANY($3::text[])""",
            self._source,
            archive.sha256,
            list(AUTOMATIC_REASONS),
        )
        await conn.execute(
            """INSERT INTO session_body_retention_holds
            (source_instance_id,archive_sha256,held_until,hold)
            VALUES($1,$2,now()+$3::double precision*interval '1 second',$4)
            ON CONFLICT(source_instance_id,archive_sha256)
            DO UPDATE SET held_until=EXCLUDED.held_until,hold=EXCLUDED.hold""",
            self._source,
            archive.sha256,
            self._hold,
            decision.hold.value,
        )
        return False
