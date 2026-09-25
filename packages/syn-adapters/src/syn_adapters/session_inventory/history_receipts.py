"""Durable backfill receipts and the bulk backfill to-do list (#1398)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    BackfillReceipt,
    BackfillReceiptConflict,
    HistoryBackfillItem,
    HistoryBackfillLease,
    RunIdentity,
)

if TYPE_CHECKING:
    from .database import Pool


class PostgresBackfillReceipts:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def ensure_ready(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(Path(__file__).with_name("history_schema.sql").read_text())

    async def existing(self, run: RunIdentity) -> tuple[BackfillReceipt, ...]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload::text FROM session_backfill_receipts
                WHERE source_instance_id=$1 AND execution_id=$2 ORDER BY materialized_seq""",
                run.source_instance_id,
                run.execution_id,
            )
        receipts = tuple(BackfillReceipt.model_validate_json(row["payload"]) for row in rows)
        if any(item.run != run for item in receipts):
            raise ValueError("stored backfill receipt crossed run scope")
        return receipts

    async def insert(self, run: RunIdentity, receipts: tuple[BackfillReceipt, ...]) -> None:
        if any(item.run != run for item in receipts):
            raise ValueError("backfill receipt belongs to another run")
        async with self._pool.acquire() as conn, conn.transaction():
            for item in receipts:
                inserted = await conn.fetch(
                    """INSERT INTO session_backfill_receipts
                    (source_instance_id,execution_id,fingerprint,snapshot_id,ordinal,payload)
                    VALUES ($1,$2,$3,$4::uuid,$5,$6::jsonb) ON CONFLICT DO NOTHING RETURNING 1""",
                    run.source_instance_id,
                    run.execution_id,
                    item.fingerprint,
                    str(item.snapshot_id),
                    item.ordinal,
                    item.model_dump_json(),
                )
                if not inserted:
                    # Raising inside the transaction rolls back every receipt.
                    raise BackfillReceiptConflict("backfill receipt already materialized")


class PostgresHistoryBackfillQueue:
    """Leased to-do rows. Work is idempotent, so a lost lease only repeats work."""

    def __init__(self, pool: Pool, source_instance_id: str) -> None:
        self._pool = pool
        self._source = source_instance_id

    async def enqueue(self, items: tuple[HistoryBackfillItem, ...]) -> int:
        if any(item.run.source_instance_id != self._source for item in items):
            raise ValueError("history backfill item belongs to another installation")
        added = 0
        async with self._pool.acquire() as conn, conn.transaction():
            for item in items:
                rows = await conn.fetch(
                    """INSERT INTO session_backfill_queue
                    (source_instance_id,execution_id,request_key) VALUES ($1,$2,$3)
                    ON CONFLICT DO NOTHING RETURNING 1""",
                    self._source,
                    item.run.execution_id,
                    item.idempotency_key,
                )
                added += len(rows)
        return added

    async def claim(self, *, lease_seconds: int) -> HistoryBackfillLease | None:
        if lease_seconds < 1:
            raise ValueError("lease duration must be positive")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """WITH candidate AS (
                    SELECT execution_id,request_key FROM session_backfill_queue
                    WHERE source_instance_id=$2 AND state='pending'
                      AND leased_until<=now() AND retry_at<=now()
                    ORDER BY retry_at,execution_id,request_key FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE session_backfill_queue q SET lease_token=q.lease_token+1,
                    attempts=q.attempts+1,
                    leased_until=now()+$1::double precision*interval '1 second'
                FROM candidate c WHERE q.source_instance_id=$2
                  AND q.execution_id=c.execution_id AND q.request_key=c.request_key
                RETURNING q.execution_id,q.request_key,q.lease_token::text,q.attempts::text""",
                lease_seconds,
                self._source,
            )
        if not rows:
            return None
        row = rows[0]
        return HistoryBackfillLease(
            item=HistoryBackfillItem(
                run=RunIdentity(source_instance_id=self._source, execution_id=row["execution_id"]),
                idempotency_key=row["request_key"],
            ),
            lease_token=int(row["lease_token"]),
            attempts=int(row["attempts"]),
        )

    async def _settle(self, lease: HistoryBackfillLease, assignment: str, *args: object) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""UPDATE session_backfill_queue SET {assignment}
                WHERE source_instance_id=$1 AND execution_id=$2 AND request_key=$3
                  AND lease_token=$4 AND state='pending'""",
                self._source,
                lease.item.run.execution_id,
                lease.item.idempotency_key,
                lease.lease_token,
                *args,
            )

    async def complete(self, lease: HistoryBackfillLease, job_id: str) -> None:
        await self._settle(lease, "state='completed',job_id=$5,leased_until='-infinity'", job_id)

    async def retry(self, lease: HistoryBackfillLease, *, retry_seconds: int) -> None:
        await self._settle(
            lease,
            "leased_until='-infinity',retry_at=now()+$5::double precision*interval '1 second'",
            retry_seconds,
        )

    async def fail(self, lease: HistoryBackfillLease, failure_code: str) -> None:
        await self._settle(
            lease, "state='failed',failure_code=$5,leased_until='-infinity'", failure_code
        )
