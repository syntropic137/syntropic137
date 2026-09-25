"""Installation-wide object policy behind the ADR-059 gateway boundary.

This adapter does not authenticate callers. Composition must restrict it to
trusted installation access; it must not be reused as a per-user permission
check if the API gains narrower principals. Revocation and deletion are keyed by
the exact archived bytes, so a decision taken through one run applies to every
run whose membership shares that object (whole-object authorization). Both are
checked on every read; a frozen inventory revision never grants access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import ArchivedTranscript, CataloguedCapture
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptAccessPort import (
        BodyTombstone,
    )

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

    async def tombstone(self, capture: CataloguedCapture) -> BodyTombstone | None:
        if capture.run.source_instance_id != self._source:
            raise PermissionError("transcript is outside this installation")
        async with self._pool.acquire() as conn:
            reason = await conn.fetchval(
                """SELECT reason FROM session_body_deletions
                WHERE source_instance_id=$1 AND archive_sha256=$2""",
                self._source,
                capture.archive.sha256,
            )
        if reason is None:
            return None
        return "deleted" if reason in ("deletion", "retraction") else "expired"

    async def revoke(self, archive: ArchivedTranscript) -> bool:
        """Persist an idempotent read tombstone; this does not erase stored bytes.

        Returns whether this call created the revocation.
        """
        async with self._pool.acquire() as conn:
            created = await conn.fetchval(
                """INSERT INTO session_transcript_revocations(source_instance_id,archive_sha256)
                VALUES ($1,$2) ON CONFLICT DO NOTHING RETURNING archive_sha256""",
                self._source,
                archive.sha256,
            )
        return created is not None
