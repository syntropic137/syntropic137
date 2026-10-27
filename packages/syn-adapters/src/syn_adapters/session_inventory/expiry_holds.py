"""What the confirmed-expiry gate is keeping, by reason, for /health (#2107).

Reads ``session_body_retention_holds``: one row per body whose automatic
expiry the gate refused, with its latest reason and logical size. A body that
was later deleted (an owner deletion, or a confirmed expiry) is not counted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .expiry_gate import ExpiryHold

if TYPE_CHECKING:
    from .database import Pool


@dataclass(frozen=True, slots=True)
class ExpiryHoldCount:
    hold: ExpiryHold
    bodies: int
    bytes: int
    """Logical (uncompressed) bytes of the held bodies, not bytes on disk."""


class PostgresExpiryHolds:
    def __init__(self, pool: Pool, source_instance_id: str) -> None:
        if not source_instance_id.strip():
            raise ValueError("expiry holds require an installation identity")
        self._pool, self._source = pool, source_instance_id

    async def summary(self) -> list[ExpiryHoldCount]:
        """One count per reason with at least one held body, in reason order."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT h.hold,count(*)::text AS bodies,COALESCE(sum(h.size),0)::text AS bytes
                FROM session_body_retention_holds h WHERE h.source_instance_id=$1
                AND NOT EXISTS(SELECT 1 FROM session_body_deletions d
                    WHERE d.source_instance_id=h.source_instance_id
                    AND d.archive_sha256=h.archive_sha256 AND d.deleted_at IS NOT NULL)
                GROUP BY h.hold""",
                self._source,
            )
        counts = {ExpiryHold(row["hold"]): (int(row["bodies"]), int(row["bytes"])) for row in rows}
        return [
            ExpiryHoldCount(hold=hold, bodies=counts[hold][0], bytes=counts[hold][1])
            for hold in ExpiryHold
            if hold in counts
        ]
