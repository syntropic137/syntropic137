"""One bounded indexed lookup overlays current restrictions on immutable pages.

Local receipts are matched by the archived byte hash. Remote receipts carry the
APSS original-content hash as their revision, so they are matched by the content
hash recorded with the deletion; a deleted body is never reported as present at
a replica just because its receipt predates the deletion. A tombstone is
effective from the moment it is recorded, before bytes are erased.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import CaptureReceipt, TranscriptBodyState

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import InventoryPage, InventoryQueryPage

    from .database import Pool

_CONTENT_HASH = re.compile(r"^sha256:[a-f0-9]{64}$")


class PostgresBodyAvailability:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def overrides(
        self, page: InventoryPage | InventoryQueryPage
    ) -> tuple[TranscriptBodyState, ...]:
        captures = [item for item in page.items if isinstance(item, CaptureReceipt)]
        hashes = sorted(
            {
                item.archived_byte_hash
                for item in captures
                if item.destination == "local" and item.archived_byte_hash is not None
            }
        )
        content = sorted(
            {
                item.transcript_revision
                for item in captures
                if item.destination == "remote"
                and item.transcript_revision is not None
                and _CONTENT_HASH.fullmatch(item.transcript_revision)
            }
        )
        if not hashes and not content:
            return ()
        if len(hashes) + len(content) > 500:
            raise ValueError("Body availability requires a bounded inventory page")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """WITH wanted AS (
                    SELECT h AS hash FROM unnest($2::text[]) AS h
                    UNION SELECT d.archive_sha256 FROM session_body_deletions d
                    WHERE d.source_instance_id=$1 AND d.content_hash=ANY($3::text[])
                )
                SELECT w.hash,d.content_hash,
                CASE WHEN d.reason IN ('deletion','retraction') THEN 'deleted'
                    WHEN d.archive_sha256 IS NOT NULL THEN 'expired'
                    ELSE 'withheld' END AS status
                FROM wanted w
                LEFT JOIN session_transcript_revocations r ON r.source_instance_id=$1
                    AND r.archive_sha256=w.hash
                LEFT JOIN session_body_deletions d ON d.source_instance_id=$1
                    AND d.archive_sha256=w.hash
                WHERE r.archive_sha256 IS NOT NULL OR d.archive_sha256 IS NOT NULL
                ORDER BY w.hash""",
                page.snapshot.run.source_instance_id,
                hashes,
                content,
            )
        return tuple(
            TranscriptBodyState.model_validate(
                {
                    "archive_sha256": row["hash"],
                    "source_content_hash": row["content_hash"],
                    "status": row["status"],
                }
            )
            for row in rows
        )
