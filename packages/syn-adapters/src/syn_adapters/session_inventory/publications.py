"""Read local publication order for bounded, optional inventory replication."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.agent_sessions import InventorySnapshot, RunIdentity

if TYPE_CHECKING:
    from .database import Pool


class InventoryPublication(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot: InventorySnapshot
    parent_snapshot_id: UUID | None
    revision_sequence: int = Field(ge=1)
    first_record_sequence: int = Field(ge=1)
    record_high_watermark: int = Field(ge=0)


class PostgresInventoryPublications:
    """Metadata only. Snapshot bodies remain independently keyset-paginated."""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def page(
        self, run: RunIdentity, *, after: int = 0, limit: int = 100
    ) -> tuple[InventoryPublication, ...]:
        if after < 0 or not 1 <= limit <= 500:
            raise ValueError("publication limit must be 1..500 and cursor nonnegative")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT s.metadata::text, p.parent_snapshot_id::text,
                p.revision_sequence::text, p.first_record_sequence::text,
                p.record_high_watermark::text FROM session_inventory_publications p
                JOIN session_inventory_snapshots s
                USING (source_instance_id,execution_id,snapshot_id)
                WHERE p.source_instance_id=$1 AND p.execution_id=$2
                AND p.revision_sequence>$3 AND s.published
                ORDER BY p.revision_sequence LIMIT $4""",
                run.source_instance_id,
                run.execution_id,
                after,
                limit,
            )
        return tuple(
            InventoryPublication(
                snapshot=InventorySnapshot.model_validate_json(row["metadata"]),
                parent_snapshot_id=UUID(row["parent_snapshot_id"])
                if row["parent_snapshot_id"] is not None
                else None,
                revision_sequence=int(row["revision_sequence"]),
                first_record_sequence=int(row["first_record_sequence"]),
                record_high_watermark=int(row["record_high_watermark"]),
            )
            for row in rows
        )
