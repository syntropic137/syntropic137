"""Fenced progress from published local snapshots into the exporter outbox."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from .publications import InventoryPublication  # noqa: TC001 - Pydantic runtime field

if TYPE_CHECKING:
    from .database import Pool


class ReplicationLeaseLost(RuntimeError):
    pass


class ReplicationLease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    publication: InventoryPublication
    offset: int = Field(ge=0)
    token: int = Field(ge=1)
    destination_id: str


class PostgresReplicationJobs:
    def __init__(self, pool: Pool, source_instance_id: str, destination_id: str) -> None:
        if any(
            not value.strip() or "\x00" in value or len(value) > 128
            for value in (source_instance_id, destination_id)
        ):
            raise ValueError("invalid replication namespace")
        self._pool, self._source, self._destination = pool, source_instance_id, destination_id

    async def discover(self, limit: int = 100) -> None:
        if not 1 <= limit <= 500:
            raise ValueError("replication discovery limit must be 1..500")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_inventory_replication_jobs
                (destination_id,source_instance_id,execution_id,snapshot_id)
                SELECT $1,p.source_instance_id,p.execution_id,p.snapshot_id
                FROM session_inventory_publications p
                WHERE p.source_instance_id=$2 AND NOT EXISTS (
                    SELECT 1 FROM session_inventory_replication_jobs j
                    WHERE j.destination_id=$1 AND j.source_instance_id=p.source_instance_id
                    AND j.execution_id=p.execution_id AND j.snapshot_id=p.snapshot_id)
                ORDER BY p.execution_id,p.revision_sequence LIMIT $3 ON CONFLICT DO NOTHING""",
                self._destination,
                self._source,
                limit,
            )

    async def claim(self, lease_seconds: int = 120) -> ReplicationLease | None:
        if lease_seconds < 1:
            raise ValueError("lease duration must be positive")
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                """WITH candidate AS (
                    SELECT j.destination_id,j.source_instance_id,j.execution_id,j.snapshot_id
                    FROM session_inventory_replication_jobs j
                    JOIN session_inventory_publications p USING(source_instance_id,execution_id,snapshot_id)
                    WHERE j.destination_id=$1 AND j.source_instance_id=$2 AND NOT j.queued
                    AND j.leased_until<=now() AND j.retry_at<=now()
                    ORDER BY j.retry_at,p.execution_id,p.revision_sequence
                    FOR UPDATE OF j SKIP LOCKED LIMIT 1
                ), claimed AS (
                    UPDATE session_inventory_replication_jobs j SET lease_token=j.lease_token+1,
                    leased_until=now()+$3::double precision*interval '1 second'
                    FROM candidate c WHERE j.destination_id=c.destination_id
                    AND j.source_instance_id=c.source_instance_id AND j.execution_id=c.execution_id
                    AND j.snapshot_id=c.snapshot_id RETURNING j.*
                ) SELECT jsonb_build_object('publication',jsonb_build_object(
                    'snapshot',s.metadata,'parent_snapshot_id',p.parent_snapshot_id,
                    'revision_sequence',p.revision_sequence,'first_record_sequence',p.first_record_sequence,
                    'record_high_watermark',p.record_high_watermark),
                    'offset',c.next_offset,'token',c.lease_token,'destination_id',c.destination_id)::text
                FROM claimed c JOIN session_inventory_publications p USING(source_instance_id,execution_id,snapshot_id)
                JOIN session_inventory_snapshots s USING(source_instance_id,execution_id,snapshot_id)
                WHERE s.published""",
                self._destination,
                self._source,
                lease_seconds,
            )
        return None if raw is None else ReplicationLease.model_validate_json(raw)

    def _scope(self, lease: ReplicationLease) -> None:
        if (
            lease.destination_id != self._destination
            or lease.publication.snapshot.run.source_instance_id != self._source
        ):
            raise ValueError("replication lease belongs to another namespace")

    async def renew(self, lease: ReplicationLease, lease_seconds: int = 120) -> None:
        self._scope(lease)
        if lease_seconds < 1:
            raise ValueError("lease duration must be positive")
        snapshot = lease.publication.snapshot
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                """UPDATE session_inventory_replication_jobs
                SET leased_until=now()+$6::double precision*interval '1 second'
                WHERE destination_id=$1 AND source_instance_id=$2 AND execution_id=$3 AND snapshot_id=$4
                AND lease_token=$5 AND leased_until>now() AND NOT queued RETURNING snapshot_id::text""",
                self._destination,
                self._source,
                snapshot.run.execution_id,
                snapshot.snapshot_id,
                lease.token,
                lease_seconds,
            )
        if result is None:
            raise ReplicationLeaseLost("replication lease expired or was superseded")

    async def advance(
        self, lease: ReplicationLease, *, next_offset: int | None, retry_seconds: int = 0
    ) -> None:
        self._scope(lease)
        total = (
            lease.publication.record_high_watermark - lease.publication.first_record_sequence + 1
        )
        offset = total if next_offset is None else next_offset
        if retry_seconds < 0 or not lease.offset <= offset <= min(total, lease.offset + 100):
            raise ValueError("invalid replication progress")
        snapshot = lease.publication.snapshot
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                """UPDATE session_inventory_replication_jobs SET next_offset=$6,queued=$7,
                leased_until='-infinity',retry_at=now()+$8::double precision*interval '1 second'
                WHERE destination_id=$1 AND source_instance_id=$2 AND execution_id=$3 AND snapshot_id=$4
                AND lease_token=$5 AND leased_until>now() AND NOT queued RETURNING snapshot_id::text""",
                self._destination,
                self._source,
                snapshot.run.execution_id,
                snapshot.snapshot_id,
                lease.token,
                offset,
                next_offset is None,
                retry_seconds,
            )
        if result is None:
            raise ReplicationLeaseLost("replication lease expired or was superseded")
