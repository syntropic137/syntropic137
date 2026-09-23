"""One bounded indexed lookup overlays current restrictions on immutable pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import CaptureReceipt, TranscriptBodyState

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import InventoryPage

    from .database import Pool


class PostgresBodyAvailability:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def overrides(self, page: InventoryPage) -> tuple[TranscriptBodyState, ...]:
        hashes = sorted(
            {
                item.archived_byte_hash
                for item in page.items
                if isinstance(item, CaptureReceipt)
                and item.destination == "local"
                and item.archived_byte_hash is not None
            }
        )
        if not hashes:
            return ()
        if len(hashes) > 500:
            raise ValueError("Body availability requires a bounded inventory page")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT h.hash,CASE WHEN r.archive_sha256 IS NOT NULL THEN 'withheld'
                ELSE 'expired' END AS status FROM unnest($2::text[]) AS h(hash)
                LEFT JOIN session_transcript_revocations r ON r.source_instance_id=$1
                    AND r.archive_sha256=h.hash
                LEFT JOIN session_body_deletions d ON d.source_instance_id=$1
                    AND d.archive_sha256=h.hash AND d.deleted_at IS NOT NULL
                WHERE r.archive_sha256 IS NOT NULL OR d.archive_sha256 IS NOT NULL
                ORDER BY h.hash""",
                page.snapshot.run.source_instance_id,
                hashes,
            )
        return tuple(
            TranscriptBodyState.model_validate(
                {"archive_sha256": row["hash"], "status": row["status"]}
            )
            for row in rows
        )
