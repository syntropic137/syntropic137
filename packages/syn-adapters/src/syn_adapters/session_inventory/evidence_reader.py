"""Durable evidence journal and at-least-once wakeup outbox (#1398).

Per-run counters are locked through commit. A database sequence alone is unsafe:
transaction N+1 can commit before N, letting a checkpoint permanently miss N.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    EvidenceBatch,
    EvidencePage,
    PendingEvidence,
    RunIdentity,
    StoredEvidenceBatch,
)

from .evidence_writes import append_locked, lock_run, observe_status

if TYPE_CHECKING:
    from .database import Pool


class PostgresSessionEvidence:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def ensure_ready(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(Path(__file__).with_name("schema.sql").read_text())

    async def append(self, batch: EvidenceBatch) -> int:
        async with self._pool.acquire() as conn, conn.transaction():
            current = await lock_run(conn, batch.evidence.run)
            return await append_locked(conn, batch, current)

    async def observe_acquisition(self, batch: EvidenceBatch) -> int:
        """Persist a monotonic status checkpoint; append only semantic transitions."""
        async with self._pool.acquire() as conn, conn.transaction():
            current = await lock_run(conn, batch.evidence.run)
            return await observe_status(conn, batch, current)

    async def watermark(self, run: RunIdentity) -> int:
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                """SELECT watermark::text FROM session_evidence_watermarks
                WHERE source_instance_id=$1 AND execution_id=$2""",
                run.source_instance_id,
                run.execution_id,
            )
        return 0 if raw is None else int(raw)

    async def read(
        self, run: RunIdentity, watermark: int, *, after: int = 0, limit: int = 100
    ) -> EvidencePage:
        if after < 0 or watermark < after or not 1 <= limit <= 500:
            raise ValueError("invalid evidence page bounds")
        if watermark > await self.watermark(run):
            raise ValueError("cannot read an uncommitted evidence watermark")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT sequence::text,payload::text FROM session_evidence_batches
                WHERE source_instance_id=$1 AND execution_id=$2 AND sequence>$3 AND sequence<=$4
                ORDER BY session_evidence_batches.sequence LIMIT $5""",
                run.source_instance_id,
                run.execution_id,
                after,
                watermark,
                limit + 1,
            )
        items = tuple(
            StoredEvidenceBatch(
                sequence=int(row["sequence"]),
                batch=EvidenceBatch.model_validate_json(row["payload"]),
            )
            for row in rows[:limit]
        )
        return EvidencePage(
            watermark=watermark,
            items=items,
            next_after=items[-1].sequence if len(rows) > limit else None,
        )

    async def pending(self, *, limit: int = 100) -> tuple[PendingEvidence, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("outbox limit must be 1..500")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT source_instance_id,execution_id,watermark::text
                FROM session_evidence_watermarks WHERE watermark>dispatched_watermark
                ORDER BY source_instance_id,execution_id LIMIT $1""",
                limit,
            )
        return tuple(
            PendingEvidence(
                run=RunIdentity(
                    source_instance_id=row["source_instance_id"], execution_id=row["execution_id"]
                ),
                watermark=int(row["watermark"]),
            )
            for row in rows
        )

    async def acknowledge_dispatch(self, item: PendingEvidence) -> None:
        async with self._pool.acquire() as conn:
            updated = await conn.fetchval(
                """UPDATE session_evidence_watermarks
                SET dispatched_watermark=GREATEST(dispatched_watermark,$3)
                WHERE source_instance_id=$1 AND execution_id=$2 AND watermark >= $3
                RETURNING dispatched_watermark::text""",
                item.run.source_instance_id,
                item.run.execution_id,
                item.watermark,
            )
        if updated is None:
            raise ValueError("cannot acknowledge evidence that has not committed")

    async def requeue(self, item: PendingEvidence) -> None:
        async with self._pool.acquire() as conn:
            updated = await conn.fetchval(
                """UPDATE session_evidence_watermarks
                SET dispatched_watermark=LEAST(dispatched_watermark,$3-1)
                WHERE source_instance_id=$1 AND execution_id=$2 AND watermark >= $3
                RETURNING dispatched_watermark::text""",
                item.run.source_instance_id,
                item.run.execution_id,
                item.watermark,
            )
        if updated is None:
            raise ValueError("cannot requeue evidence that has not committed")
