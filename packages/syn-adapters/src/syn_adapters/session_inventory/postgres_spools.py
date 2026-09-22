"""Replay-safe capture discovery and fenced cursors survive process restarts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    CaptureSpool,
    CaptureSpoolLease,
    CaptureSpoolLeaseLost,
)

if TYPE_CHECKING:
    from .database import Pool


class PostgresCaptureSpools:
    def __init__(self, pool: Pool, source_instance_id: str) -> None:
        self._pool = pool
        self._source = source_instance_id

    async def project(self, spool: CaptureSpool) -> None:
        if spool.run.source_instance_id != self._source:
            raise ValueError("Capture spool belongs to another installation")
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """INSERT INTO session_capture_spools(source_instance_id,session_id,payload)
                VALUES ($1,$2,$3::jsonb) ON CONFLICT DO NOTHING""",
                spool.run.source_instance_id,
                spool.session_id,
                spool.model_dump_json(),
            )
            raw = await conn.fetchval(
                "SELECT payload::text FROM session_capture_spools WHERE source_instance_id=$1 AND session_id=$2",
                spool.run.source_instance_id,
                spool.session_id,
            )
            if raw is None or CaptureSpool.model_validate_json(raw) != spool:
                raise ValueError("Capture spool identity was rebound to a different session scope")

    async def claim(self, *, lease_seconds: int) -> CaptureSpoolLease | None:
        if lease_seconds < 1:
            raise ValueError("Lease duration must be positive")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """WITH candidate AS (
                    SELECT source_instance_id,session_id FROM session_capture_spools
                    WHERE leased_until<=now() AND retry_at<=now() AND source_instance_id=$2
                    ORDER BY retry_at,source_instance_id,session_id FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE session_capture_spools s SET lease_token=s.lease_token+1,
                    leased_until=now()+$1::double precision*interval '1 second'
                FROM candidate c WHERE s.source_instance_id=c.source_instance_id AND s.session_id=c.session_id
                RETURNING s.payload::text,s.lease_token::text,s.after_sequence::text,s.watermark::text,
                    s.child_after_sequence::text,s.child_watermark::text""",
                lease_seconds,
                self._source,
            )
        if not rows:
            return None
        row = rows[0]
        return CaptureSpoolLease(
            spool=CaptureSpool.model_validate_json(row["payload"]),
            token=int(row["lease_token"]),
            after=int(row["after_sequence"]),
            watermark=None if row["watermark"] is None else int(row["watermark"]),
            child_after=int(row["child_after_sequence"]),
            child_watermark=None if row["child_watermark"] is None else int(row["child_watermark"]),
        )

    async def renew(self, lease: CaptureSpoolLease, *, lease_seconds: int) -> None:
        if lease_seconds < 1 or lease.spool.run.source_instance_id != self._source:
            raise ValueError("Invalid capture lease renewal")
        async with self._pool.acquire() as conn:
            renewed = await conn.fetchval(
                """UPDATE session_capture_spools SET leased_until=now()+$4::double precision*interval '1 second'
                WHERE source_instance_id=$1 AND session_id=$2 AND lease_token=$3 AND leased_until>now()
                RETURNING session_id""",
                self._source,
                lease.spool.session_id,
                lease.token,
                lease_seconds,
            )
        if renewed is None:
            raise CaptureSpoolLeaseLost("Capture cursor lease expired or was superseded")

    async def advance(
        self,
        lease: CaptureSpoolLease,
        *,
        after: int,
        watermark: int | None,
        retry_seconds: int,
    ) -> None:
        if lease.spool.run.source_instance_id != self._source:
            raise ValueError("Capture lease belongs to another installation")
        _validate_progress(lease, after, watermark, retry_seconds)
        async with self._pool.acquire() as conn:
            changed = await conn.fetchval(
                """UPDATE session_capture_spools SET after_sequence=$4,watermark=$5,
                leased_until='-infinity',retry_at=now()+$6::double precision*interval '1 second'
                WHERE source_instance_id=$1 AND session_id=$2 AND lease_token=$3 AND leased_until>now()
                RETURNING session_id""",
                lease.spool.run.source_instance_id,
                lease.spool.session_id,
                lease.token,
                after,
                watermark,
                retry_seconds,
            )
        if changed is None:
            raise CaptureSpoolLeaseLost("Capture cursor lease expired or was superseded")

    async def advance_children(
        self, lease: CaptureSpoolLease, *, after: int, watermark: int | None
    ) -> None:
        if lease.spool.run.source_instance_id != self._source:
            raise ValueError("Capture lease belongs to another installation")
        child_cursor = lease.model_copy(
            update={
                "after": lease.child_after,
                "watermark": lease.child_watermark,
            }
        )
        _validate_progress(child_cursor, after, watermark, 0)
        async with self._pool.acquire() as conn:
            changed = await conn.fetchval(
                """UPDATE session_capture_spools
                SET child_after_sequence=$4,child_watermark=$5
                WHERE source_instance_id=$1 AND session_id=$2 AND lease_token=$3
                  AND leased_until>now() AND child_after_sequence=$6
                  AND child_watermark IS NOT DISTINCT FROM $7::bigint
                RETURNING session_id""",
                self._source,
                lease.spool.session_id,
                lease.token,
                after,
                watermark,
                lease.child_after,
                lease.child_watermark,
            )
        if changed is None:
            raise CaptureSpoolLeaseLost("Child cursor lease expired or progress was superseded")


def _validate_progress(
    lease: CaptureSpoolLease,
    after: int,
    watermark: int | None,
    retry_seconds: int,
) -> None:
    if after < lease.after or retry_seconds < 0 or (watermark is not None and watermark < after):
        raise ValueError("Invalid capture progress")
    if lease.watermark is not None and watermark not in (None, lease.watermark):
        raise ValueError("Cannot change watermark during a traversal")
    if watermark is None and lease.watermark is not None and after != lease.watermark:
        raise ValueError("Cannot finish an incomplete capture traversal")
