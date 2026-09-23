"""Bounded, restart-safe local body expiry; discovery history is retained."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import ArchivedTranscript

from .exporter_transport import original_envelope_hash

if TYPE_CHECKING:
    from pathlib import Path

    from .database import Pool
    from .local_archive import LocalSessionTranscriptArchive


class LocalBodyRetention:
    def __init__(
        self,
        pool: Pool,
        archive: LocalSessionTranscriptArchive,
        source: str,
        *,
        age_seconds: int,
        exporter_binary: Path | None = None,
    ) -> None:
        if age_seconds < 1 or not source.strip():
            raise ValueError("body retention requires a positive age and installation identity")
        self._pool, self._archive, self._source = pool, archive, source
        self._age = age_seconds
        self._exporter = exporter_binary

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
                """SELECT d.archive::text,d.content_hash,
                (EXISTS(SELECT 1 FROM session_capture_catalog c
                    WHERE c.source_instance_id=d.source_instance_id
                    AND c.payload->'archive'->>'sha256'=d.archive_sha256
                    AND c.payload->>'content_format'='envelope'))::text AS envelope
                FROM session_body_deletions d
                WHERE source_instance_id=$1 AND deleted_at IS NULL
                ORDER BY requested_at,archive_sha256 FOR UPDATE SKIP LOCKED LIMIT 1""",
                self._source,
            )
            if not rows:
                return False
            archive = ArchivedTranscript.model_validate_json(rows[0]["archive"])
            if rows[0]["envelope"] == "true" and rows[0]["content_hash"] is None:
                if self._exporter is None:
                    raise RuntimeError("Envelope expiry requires the standard exporter")
                body = await self._archive.get(archive)
                if body is None:
                    raise RuntimeError("Cannot identify an absent envelope for deletion")
                content_hash = await original_envelope_hash(self._exporter, body)
                await conn.execute(
                    """UPDATE session_body_deletions SET content_hash=$3
                    WHERE source_instance_id=$1 AND archive_sha256=$2""",
                    self._source,
                    archive.sha256,
                    content_hash,
                )
                # Commit the deletion key before any body removal. The next
                # bounded step can delete safely after an intervening restart.
                return True
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
