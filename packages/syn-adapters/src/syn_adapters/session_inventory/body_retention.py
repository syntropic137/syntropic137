"""Bounded, restart-safe local body expiry; discovery history is retained."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import ArchivedTranscript

if TYPE_CHECKING:
    from .database import Pool
    from .local_archive import LocalSessionTranscriptArchive


class LocalBodyRetention:
    def __init__(
        self, pool: Pool, archive: LocalSessionTranscriptArchive, source: str, *, age_seconds: int
    ) -> None:
        if age_seconds < 1 or not source.strip():
            raise ValueError("body retention requires a positive age and installation identity")
        self._pool, self._archive, self._source = pool, archive, source
        self._age = age_seconds

    async def discover(self, limit: int = 100) -> None:
        if not 1 <= limit <= 500:
            raise ValueError("retention discovery limit must be 1..500")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive)
                SELECT c.source_instance_id,c.payload->'archive'->>'sha256',c.payload->'archive'
                FROM session_capture_catalog c
                WHERE c.source_instance_id=$1
                AND c.created_at<=now()-$2::double precision*interval '1 second'
                AND NOT EXISTS(SELECT 1 FROM session_body_deletions d
                    WHERE d.source_instance_id=c.source_instance_id
                    AND d.archive_sha256=c.payload->'archive'->>'sha256')
                ORDER BY c.created_at,c.producer_id,c.capture_id
                LIMIT $3 ON CONFLICT DO NOTHING""",
                self._source,
                self._age,
                limit,
            )

    async def step(self) -> bool:
        await self.discover()
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """SELECT archive::text FROM session_body_deletions
                WHERE source_instance_id=$1 AND deleted_at IS NULL
                ORDER BY requested_at,archive_sha256 FOR UPDATE SKIP LOCKED LIMIT 1""",
                self._source,
            )
            if not rows:
                return False
            archive = ArchivedTranscript.model_validate_json(rows[0]["archive"])
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
