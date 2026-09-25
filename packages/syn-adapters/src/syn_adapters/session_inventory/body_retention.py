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
    """Live-only cleanup owner for local transcript bodies.

    Deletion requests come from three sources, all recorded as durable SQL
    tombstones before any byte is removed: age expiry, the archive byte quota,
    and owner deletion/retraction through the API. ``step`` executes exactly one
    pending request whatever its source, so owner deletions run even when no
    automatic retention is configured.
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

    async def discover(self, limit: int = 100) -> None:
        if not 1 <= limit <= 500:
            raise ValueError("retention discovery limit must be 1..500")
        if self._age is not None:
            await self._discover_age(limit)
        if self._max_bytes is not None:
            await self._discover_quota(limit)

    async def _discover_age(self, limit: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive,reason)
                SELECT c.source_instance_id,c.payload->'archive'->>'sha256',c.payload->'archive',
                'retention_age'
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

    async def _discover_quota(self, limit: int) -> None:
        """Keep the newest retained objects within the byte quota; evict the oldest.

        Size counts each exact object once however many captures share it.
        Objects already tombstoned no longer count against the quota.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """WITH objects AS (
                    SELECT c.payload->'archive'->>'sha256' AS sha,
                    min((c.payload->'archive')::text) AS archive,
                    max((c.payload->'archive'->>'size')::bigint) AS size,
                    min(c.created_at) AS first_seen
                    FROM session_capture_catalog c
                    WHERE c.source_instance_id=$1
                    AND NOT EXISTS(SELECT 1 FROM session_body_deletions d
                        WHERE d.source_instance_id=c.source_instance_id
                        AND d.archive_sha256=c.payload->'archive'->>'sha256')
                    GROUP BY 1
                ), ranked AS (
                    SELECT sha,archive,first_seen,
                    sum(size) OVER (ORDER BY first_seen DESC,sha DESC) AS newer_total
                    FROM objects
                )
                INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive,reason)
                SELECT $1,sha,archive::jsonb,'retention_quota' FROM ranked
                WHERE newer_total>$2 ORDER BY first_seen,sha LIMIT $3
                ON CONFLICT DO NOTHING""",
                self._source,
                self._max_bytes,
                limit,
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
