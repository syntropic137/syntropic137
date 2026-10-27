"""Bounded, restart-safe local body expiry; discovery history is retained."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import ArchivedTranscript
from syn_domain.contexts.agent_sessions.ports.SessionArchiveSinkPort import UploadedRevision

from .deletion_fence import lock_tombstones_xact
from .expiry_gate import ExpiryHold
from .exporter_transport import original_envelope_hash

if TYPE_CHECKING:
    from pathlib import Path

    from .database import Pool
    from .expiry_gate import ConfirmedExpiryGate
    from .local_archive import LocalSessionTranscriptArchive

AUTOMATIC_REASONS = ("retention_age", "retention_quota")

# Under the gate a body is eligible only when every capture it backs is the
# newest revision of its run transcript (the #2110 delivery order) AND that
# delivery was acknowledged remotely, with the content hash persisted before
# upload. Older revisions are never eligible (#2107 R1). The gate still
# confirms with the archive right before deleting.
_UPLOADED = """COALESCE(j.queued AND j.receipt_recorded AND NOT j.cancelled
    AND j.content_hash IS NOT NULL AND u.payload->>'native_id' IS NOT NULL, FALSE)"""
_NEWEST = """NOT EXISTS(SELECT 1 FROM session_capture_catalog n
        WHERE n.source_instance_id=u.source_instance_id
        AND n.payload->'run'->>'execution_id'=u.payload->'run'->>'execution_id'
        AND n.payload->>'harness'=u.payload->>'harness'
        AND n.payload->>'native_id'=u.payload->>'native_id'
        AND n.payload->>'content_format'='envelope'
        AND ((n.payload->'archive'->>'size')::bigint,n.created_at,n.producer_id,n.capture_id)
            > ((u.payload->'archive'->>'size')::bigint,u.created_at,u.producer_id,u.capture_id))"""
_ELIGIBLE = f"({_UPLOADED} AND {_NEWEST})"
_DUE = """FROM session_capture_catalog c
    WHERE c.source_instance_id=$1
    AND NOT EXISTS(SELECT 1 FROM session_body_deletions d
        WHERE d.source_instance_id=c.source_instance_id
        AND d.archive_sha256=c.payload->'archive'->>'sha256')
    GROUP BY 1"""
_OBJECTS = """SELECT c.payload->'archive'->>'sha256' AS sha,
    min((c.payload->'archive')::text) AS archive,
    max((c.payload->'archive'->>'size')::bigint) AS size,
    max(c.created_at) AS last_seen"""
# Age: an object expires only when its NEWEST referencing capture has aged out,
# since one content-addressed object can back captures acquired far apart.
_AGE_CANDIDATES = f"""WITH candidates AS ({_OBJECTS} {_DUE}
    HAVING max(c.created_at)<=now()-$2::double precision*interval '1 second')"""
# Quota: keep the most recently referenced objects within the byte quota; each
# exact object counts once, and tombstoned objects no longer count.
_QUOTA_CANDIDATES = f"""WITH objects AS ({_OBJECTS} {_DUE}),
    ranked AS (SELECT sha,archive,size,last_seen,
        sum(size) OVER (ORDER BY last_seen DESC,sha DESC) AS newer_total FROM objects),
    candidates AS (SELECT sha,archive,size,last_seen FROM ranked WHERE newer_total>$2)"""
_NOT_HELD = """NOT EXISTS(SELECT 1 FROM session_body_retention_holds h
    WHERE h.source_instance_id=$1 AND h.archive_sha256=sha AND h.held_until>now())"""
_BACKING = """FROM session_capture_catalog u
    LEFT JOIN session_capture_delivery_jobs j ON j.destination_id=$DEST
    AND j.source_instance_id=u.source_instance_id AND j.producer_id=u.producer_id
    AND j.capture_id=u.capture_id
    WHERE u.source_instance_id=$1 AND u.payload->'archive'->>'sha256'=$SHA"""


def _validate(
    source: str,
    age_seconds: int | None,
    max_bytes: int | None,
    hold_seconds: int,
    max_confirms: int,
) -> None:
    if not source.strip():
        raise ValueError("body retention requires an installation identity")
    if (age_seconds is not None and age_seconds < 1) or (max_bytes is not None and max_bytes < 1):
        raise ValueError("body retention quotas must be positive when configured")
    if hold_seconds < 1 or max_confirms < 1:
        raise ValueError("expiry hold and confirmation bound must be positive")


class LocalBodyRetention:
    """Live-only cleanup owner for local transcript bodies.

    Deletion requests come from three sources, all recorded as durable SQL
    tombstones before any byte is removed: age expiry, the archive byte quota,
    and owner deletion/retraction through the API. ``step`` executes exactly one
    pending request whatever its source, so owner deletions run even when no
    automatic retention is configured.

    With a ``gate`` (#2107, off by default), automatic expiry never deletes
    bytes the remote archive has not confirmed: discovery only tombstones the
    newest uploaded revision, and the gate confirms each uploaded revision
    immediately before deletion, with no lock held while it waits. A held
    expiry withdraws its own tombstone under the deletion fence and is not
    rediscovered until ``hold_seconds`` pass. Owner deletions and retractions
    are never gated, and neither is an expiry whose filesystem deletion
    already began. At most ``max_confirms`` confirmations run per drain.
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
        max_confirms: int = 4,
    ) -> None:
        _validate(source, age_seconds, max_bytes, hold_seconds, max_confirms)
        self._pool, self._archive, self._source = pool, archive, source
        self._age = age_seconds
        self._max_bytes = max_bytes
        self._exporter = exporter_binary
        if gate is not None and not (destination_id and destination_id.strip()):
            raise ValueError("gated body expiry requires the capture destination")
        self._gate, self._destination, self._hold = gate, destination_id, hold_seconds
        self._max_confirms = self._confirms_left = max_confirms

    async def discover(self, limit: int = 100) -> None:
        if not 1 <= limit <= 500:
            raise ValueError("retention discovery limit must be 1..500")
        if self._age is not None:
            await self._discover(_AGE_CANDIDATES, "retention_age", self._age, limit)
        if self._max_bytes is not None:
            await self._discover(_QUOTA_CANDIDATES, "retention_quota", self._max_bytes, limit)

    async def _discover(self, candidates: str, reason: str, bound: int, limit: int) -> None:
        """Tombstone due objects; under the gate, record why ineligible ones stay.

        ``candidates`` is a CTE named ``candidates`` of due objects (age: every
        referencing capture past the age; quota: the oldest-referenced objects
        beyond the byte quota). Ungated, every candidate is tombstoned as before.
        Gated, only eligible candidates are tombstoned and the rest are held:
        an older revision for good, a newest one not yet uploaded until
        ``hold_seconds`` pass. Holds are what the session store health reports.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await lock_tombstones_xact(conn, self._source)
            if self._gate is None or self._destination is None:
                await conn.execute(
                    f"""{candidates}
                    INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive,reason)
                    SELECT $1,sha,archive::jsonb,'{reason}' FROM candidates
                    ORDER BY last_seen,sha LIMIT $3 ON CONFLICT DO NOTHING""",
                    self._source,
                    bound,
                    limit,
                )
                return
            backing = _BACKING.replace("$DEST", "$4").replace("$SHA", "sha")
            await conn.execute(
                f"""{candidates}
                INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive,reason)
                SELECT $1,sha,archive::jsonb,'{reason}' FROM candidates
                WHERE {_NOT_HELD} AND NOT EXISTS(SELECT 1 {backing} AND NOT {_ELIGIBLE})
                ORDER BY last_seen,sha LIMIT $3 ON CONFLICT DO NOTHING""",
                self._source,
                bound,
                limit,
                self._destination,
            )
            await conn.execute(
                f"""{candidates}, judged AS (
                    SELECT sha,size,last_seen,
                    EXISTS(SELECT 1 {backing} AND NOT {_NEWEST}) AS older
                    FROM candidates
                    WHERE {_NOT_HELD} AND EXISTS(SELECT 1 {backing} AND NOT {_ELIGIBLE})
                )
                INSERT INTO session_body_retention_holds
                (source_instance_id,archive_sha256,held_until,hold,size)
                SELECT $1,sha,
                CASE WHEN older THEN 'infinity'::timestamptz
                    ELSE now()+$5::double precision*interval '1 second' END,
                CASE WHEN older THEN '{ExpiryHold.OLDER_REVISION.value}'
                    ELSE '{ExpiryHold.NOT_UPLOADED.value}' END,
                size FROM judged ORDER BY last_seen,sha LIMIT $3
                ON CONFLICT(source_instance_id,archive_sha256) DO UPDATE
                SET held_until=EXCLUDED.held_until,hold=EXCLUDED.hold,size=EXCLUDED.size""",
                self._source,
                bound,
                limit,
                self._destination,
                self._hold,
            )

    async def drain(self, max_steps: int = 20) -> int:
        """Execute up to ``max_steps`` pending deletions; stop early when idle."""
        if not 1 <= max_steps <= 500:
            raise ValueError("retention step bound must be 1..500")
        await self.discover()
        self._confirms_left = self._max_confirms
        done = 0
        while done < max_steps and await self._execute_one():
            done += 1
        return done

    async def step(self) -> bool:
        await self.discover()
        self._confirms_left = self._max_confirms
        return await self._execute_one()

    async def _execute_one(self) -> bool:
        if self._gate is None:
            return await self._finalize(None)
        pending = await self._next_pending()
        if pending is None:
            return False
        archive, reason = pending
        # A marker means deletion already began: a crash after unlink, or an
        # owner request that found this row. Finish it; never withdraw it.
        if reason in AUTOMATIC_REASONS and not await self._archive.is_deleted(archive):
            if self._confirms_left < 1:
                return False
            self._confirms_left -= 1
            hold = await self._decide(archive)
            if hold is not None and await self._withdraw(archive, hold):
                return True
        await self._finalize(archive.sha256)
        return True

    async def _next_pending(self) -> tuple[ArchivedTranscript, str] | None:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT archive::text,reason FROM session_body_deletions
                WHERE source_instance_id=$1 AND deleted_at IS NULL
                ORDER BY requested_at,archive_sha256 LIMIT 1""",
                self._source,
            )
        if not rows:
            return None
        return ArchivedTranscript.model_validate_json(rows[0]["archive"]), rows[0]["reason"]

    async def _finalize(self, sha256: str | None) -> bool:
        """Erase one pending body (``sha256``, or the oldest) and acknowledge it."""
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
                    AND j.queued AND j.content_hash IS NULL))::text AS legacy
                FROM session_body_deletions d
                WHERE source_instance_id=$1 AND deleted_at IS NULL
                AND ($2::text IS NULL OR archive_sha256=$2)
                ORDER BY requested_at,archive_sha256 FOR UPDATE SKIP LOCKED LIMIT 1""",
                self._source,
                sha256,
            )
            if not rows:
                return False
            archive = ArchivedTranscript.model_validate_json(rows[0]["archive"])
            content_hash = rows[0]["content_hash"]
            if content_hash is None and rows[0]["legacy"] == "true":
                content_hash = await self._legacy_hash(archive)
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
            # A deleted body is no longer held, whatever an earlier pass decided.
            await conn.execute(
                """DELETE FROM session_body_retention_holds
                WHERE source_instance_id=$1 AND archive_sha256=$2""",
                self._source,
                archive.sha256,
            )
        return True

    async def _legacy_hash(self, archive: ArchivedTranscript) -> str | None:
        """Deliveries queued before content hashes were recorded at enqueue time:
        derive the replica deletion key while bytes still exist. Absent bytes
        cannot be hashed; the replica state reports it as unresolvable instead
        of blocking erasure forever.
        """
        body = await self._archive.get(archive)
        if body is None:
            return None
        if self._exporter is None:
            raise RuntimeError("Legacy envelope expiry requires the standard exporter")
        return await original_envelope_hash(self._exporter, body)

    async def _decide(self, archive: ArchivedTranscript) -> ExpiryHold | None:
        """Ask the gate about one automatic expiry, holding no lock while it waits."""
        if self._gate is None or self._destination is None:
            return None
        backing = _BACKING.replace("$DEST", "$3").replace("$SHA", "$2")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT u.payload->>'harness' AS harness,
                u.payload->>'native_id' AS native_id, j.content_hash,
                ({_UPLOADED})::text AS uploaded, ({_NEWEST})::text AS newest {backing}""",
                self._source,
                archive.sha256,
                self._destination,
            )
        ineligible = None
        if any(row["newest"] != "true" for row in rows):
            ineligible = ExpiryHold.OLDER_REVISION
        elif not rows or any(row["uploaded"] != "true" for row in rows):
            ineligible = ExpiryHold.NOT_UPLOADED
        elif await self._archive.is_splice_base(archive):
            ineligible = ExpiryHold.SPLICE_BASE
        # One revision per qualified identity and hash: several runs can hold
        # the same transcript bytes, and the archive stores them once.
        uploaded = sorted(
            {(row["harness"], row["native_id"], row["content_hash"]) for row in rows}
            if ineligible is None
            else set()
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
            ineligible=ineligible,
        )
        return decision.hold

    async def _withdraw(self, archive: ArchivedTranscript, hold: ExpiryHold) -> bool:
        """Withdraw a held automatic expiry; False when it is, or became, owner intent.

        Under the exclusive deletion fence, so an owner request either finished
        first (its archive marker exists, or its reason replaced this one) or
        waits and records its own tombstone after this one is gone.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await lock_tombstones_xact(conn, self._source)
            if await self._archive.is_deleted(archive):
                return False
            withdrawn = await conn.fetchval(
                """DELETE FROM session_body_deletions WHERE source_instance_id=$1
                AND archive_sha256=$2 AND deleted_at IS NULL AND reason=ANY($3::text[])
                RETURNING archive_sha256""",
                self._source,
                archive.sha256,
                list(AUTOMATIC_REASONS),
            )
            if withdrawn is None:
                return False
            # An older revision never becomes the newest again: held for good.
            await conn.execute(
                """INSERT INTO session_body_retention_holds
                (source_instance_id,archive_sha256,held_until,hold,size)
                VALUES($1,$2,CASE WHEN $4=$6 THEN 'infinity'::timestamptz
                    ELSE now()+$3::double precision*interval '1 second' END,$4,$5)
                ON CONFLICT(source_instance_id,archive_sha256) DO UPDATE
                SET held_until=EXCLUDED.held_until,hold=EXCLUDED.hold,size=EXCLUDED.size""",
                self._source,
                archive.sha256,
                self._hold,
                hold.value,
                archive.size,
                ExpiryHold.OLDER_REVISION.value,
            )
        return True
