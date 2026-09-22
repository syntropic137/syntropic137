"""Installation-wide object policy behind the ADR-059 gateway boundary.

This adapter does not authenticate callers. Composition must restrict it to
trusted installation access; it must not be reused as a per-user permission
check if the API gains narrower principals. Revocation is checked on every read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import ArchivedTranscript, CataloguedCapture

    from .database import Pool


class InstallationTranscriptAccess:
    def __init__(self, pool: Pool, source_instance_id: str) -> None:
        self._pool = pool
        self._source = source_instance_id

    async def require_read(self, capture: CataloguedCapture) -> None:
        if capture.run.source_instance_id != self._source:
            raise PermissionError("transcript is outside this installation")
        async with self._pool.acquire() as conn:
            revoked = await conn.fetchval(
                """SELECT archive_sha256 FROM session_transcript_revocations
                WHERE source_instance_id=$1 AND archive_sha256=$2""",
                self._source,
                capture.archive.sha256,
            )
        if revoked is not None:
            raise PermissionError("transcript revision access revoked")

    async def revoke(self, archive: ArchivedTranscript) -> None:
        """Persist an idempotent read tombstone; this does not erase stored bytes."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_transcript_revocations(source_instance_id,archive_sha256)
                VALUES ($1,$2) ON CONFLICT DO NOTHING""",
                self._source,
                archive.sha256,
            )
