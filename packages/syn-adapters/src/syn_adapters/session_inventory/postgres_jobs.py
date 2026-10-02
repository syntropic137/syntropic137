"""Projection writes stay pure; lease and publication checks share one transaction."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    InventoryJob,
    InventoryJobLease,
    InventoryLeaseLost,
    InventoryPublicationConflict,
    InventorySnapshot,
    RunIdentity,
)

from .postgres_publication import publish_snapshot

if TYPE_CHECKING:
    from .database import Pool


class PostgresSessionInventoryJobs:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def ensure_ready(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(Path(__file__).with_name("schema.sql").read_text())

    async def project(self, job: InventoryJob) -> None:
        run = job.state.request.run
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_inventory_jobs AS j
                (job_id,source_instance_id,execution_id,global_position,stage,payload)
                VALUES ($1,$2,$3,$4,$5,$6::jsonb)
                ON CONFLICT (job_id) DO UPDATE SET
                global_position=EXCLUDED.global_position,stage=EXCLUDED.stage,payload=EXCLUDED.payload,
                lease_token=j.lease_token+1,leased_until='-infinity',retry_at='-infinity'
                WHERE j.global_position < EXCLUDED.global_position""",
                job.job_id,
                run.source_instance_id,
                run.execution_id,
                job.global_position,
                job.state.stage.value,
                job.model_dump_json(),
            )

    async def get(self, job_id: str) -> InventoryJob | None:
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                "SELECT payload::text FROM session_inventory_jobs WHERE job_id=$1", job_id
            )
        return None if raw is None else InventoryJob.model_validate_json(raw)

    async def find_ids(self, source_instance_id: str, prefix: str) -> tuple[str, ...]:
        if not prefix or len(prefix) > 36:
            return ()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT job_id FROM session_inventory_jobs
                WHERE source_instance_id=$1 AND job_id LIKE $3
                ORDER BY (job_id=$2) DESC,job_id LIMIT 2""",
                source_instance_id,
                prefix,
                prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
            )
        ids = tuple(row["job_id"] for row in rows)
        return (prefix,) if prefix in ids else ids

    async def latest(self, run: RunIdentity) -> InventoryJob | None:
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                """SELECT payload::text FROM session_inventory_jobs
                WHERE source_instance_id=$1 AND execution_id=$2 ORDER BY global_position DESC LIMIT 1""",
                run.source_instance_id,
                run.execution_id,
            )
        return None if raw is None else InventoryJob.model_validate_json(raw)

    async def claim(self, *, lease_seconds: int) -> InventoryJobLease | None:
        if lease_seconds < 1:
            raise ValueError("lease duration must be positive")
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """WITH candidate AS (
                SELECT job_id FROM session_inventory_jobs
                WHERE stage IN ('pending','publishing') AND retry_at<=now() AND leased_until<=now()
                ORDER BY retry_at,global_position FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE session_inventory_jobs j SET lease_token=j.lease_token+1,
                leased_until=now()+$1::double precision*interval '1 second'
                FROM candidate WHERE j.job_id=candidate.job_id
                RETURNING j.payload::text,j.lease_token::text""",
                lease_seconds,
            )
        if not rows:
            return None
        return InventoryJobLease(
            job=InventoryJob.model_validate_json(rows[0]["payload"]),
            token=int(rows[0]["lease_token"]),
        )

    async def renew(self, lease: InventoryJobLease, *, lease_seconds: int) -> None:
        if lease_seconds < 1:
            raise ValueError("lease duration must be positive")
        async with self._pool.acquire() as conn:
            updated = await conn.fetchval(
                """UPDATE session_inventory_jobs SET leased_until=now()+$3::double precision*interval '1 second'
                WHERE job_id=$1 AND lease_token=$2 AND leased_until>now() RETURNING job_id""",
                lease.job.job_id,
                lease.token,
                lease_seconds,
            )
        if updated is None:
            raise InventoryLeaseLost("inventory lease expired or was superseded")

    async def release(self, lease: InventoryJobLease, *, retry_seconds: int) -> None:
        if retry_seconds < 0:
            raise ValueError("retry delay cannot be negative")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE session_inventory_jobs SET leased_until='-infinity',
                retry_at=now()+$3::double precision*interval '1 second'
                WHERE job_id=$1 AND lease_token=$2""",
                lease.job.job_id,
                lease.token,
                retry_seconds,
            )

    async def publish(self, lease: InventoryJobLease) -> None:
        request = lease.job.state.request
        async with self._pool.acquire() as conn, conn.transaction():
            raw = await conn.fetchval(
                """SELECT payload::text FROM session_inventory_jobs
                WHERE job_id=$1 AND lease_token=$2 AND leased_until>now() AND stage='publishing'
                FOR UPDATE""",
                lease.job.job_id,
                lease.token,
            )
            if raw is None or InventoryJob.model_validate_json(raw) != lease.job:
                raise InventoryLeaseLost("publication requires the current publishing lease")
            metadata = await conn.fetchval(
                """SELECT metadata::text FROM session_inventory_snapshots
                WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3""",
                request.run.source_instance_id,
                request.run.execution_id,
                request.snapshot_id,
            )
            if metadata is None:
                raise InventoryPublicationConflict("publishing job has no staged snapshot")
            snapshot = InventorySnapshot.model_validate_json(metadata)
            if (snapshot.revision, snapshot.resolver_version, snapshot.evidence_watermark) != (
                lease.job.state.revision,
                request.resolver_version,
                request.evidence_watermark,
            ):
                raise InventoryPublicationConflict(
                    "staged snapshot does not match the publishing job"
                )
            await publish_snapshot(conn, request.run, request.snapshot_id, request.expected_head)
