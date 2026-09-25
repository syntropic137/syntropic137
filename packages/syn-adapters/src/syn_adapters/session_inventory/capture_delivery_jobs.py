"""Fenced local transfer from the capture catalog to the exporter's durable queue."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.agent_sessions import CataloguedCapture  # noqa: TC001

if TYPE_CHECKING:
    from .database import Connection, Pool


class CaptureDeliveryLeaseLost(RuntimeError):
    pass


class CaptureDeliveryLease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    capture: CataloguedCapture
    destination_id: str
    token: int = Field(ge=1)


class PostgresCaptureDeliveryJobs:
    def __init__(self, pool: Pool, source_instance_id: str, destination_id: str) -> None:
        if any(
            not value.strip() or "\0" in value or len(value) > 128
            for value in (source_instance_id, destination_id)
        ):
            raise ValueError("invalid capture delivery namespace")
        self._pool, self._source, self._destination = pool, source_instance_id, destination_id

    async def discover(self, limit: int = 100) -> None:
        if not 1 <= limit <= 500:
            raise ValueError("capture discovery limit must be 1..500")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_capture_delivery_jobs
                (destination_id,source_instance_id,producer_id,capture_id)
                SELECT $1,c.source_instance_id,c.producer_id,c.capture_id FROM session_capture_catalog c
                WHERE c.source_instance_id=$2 AND c.payload->>'content_format'='envelope'
                AND c.payload->>'native_id' IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM session_body_deletions d
                    WHERE d.source_instance_id=c.source_instance_id
                    AND d.archive_sha256=c.payload->'archive'->>'sha256')
                AND NOT EXISTS (
                    SELECT 1 FROM session_capture_delivery_jobs j WHERE j.destination_id=$1
                    AND j.source_instance_id=c.source_instance_id AND j.producer_id=c.producer_id AND j.capture_id=c.capture_id)
                ORDER BY c.created_at,c.producer_id,c.capture_id LIMIT $3 ON CONFLICT DO NOTHING""",
                self._destination,
                self._source,
                limit,
            )

    async def claim(self, lease_seconds: int = 120) -> CaptureDeliveryLease | None:
        if lease_seconds < 1:
            raise ValueError("capture lease duration must be positive")
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                """WITH candidate AS (
                SELECT j.destination_id,j.source_instance_id,j.producer_id,j.capture_id
                FROM session_capture_delivery_jobs j JOIN session_capture_catalog k
                USING(source_instance_id,producer_id,capture_id)
                WHERE j.destination_id=$1 AND j.source_instance_id=$2 AND NOT j.cancelled
                AND NOT j.queued AND j.leased_until<=now() AND j.retry_at<=now()
                -- A tombstone recorded before cancellation still wins over a retry.
                AND NOT EXISTS (SELECT 1 FROM session_body_deletions d
                    WHERE d.source_instance_id=k.source_instance_id
                    AND d.archive_sha256=k.payload->'archive'->>'sha256')
                ORDER BY j.retry_at,j.producer_id,j.capture_id
                FOR UPDATE OF j SKIP LOCKED LIMIT 1
            ), claimed AS (
                UPDATE session_capture_delivery_jobs j SET lease_token=j.lease_token+1,
                leased_until=now()+$3::double precision*interval '1 second'
                FROM candidate c WHERE j.destination_id=c.destination_id AND j.source_instance_id=c.source_instance_id
                AND j.producer_id=c.producer_id AND j.capture_id=c.capture_id RETURNING j.*
            ) SELECT jsonb_build_object('capture',a.payload,'destination_id',c.destination_id,'token',c.lease_token)::text
                FROM claimed c JOIN session_capture_catalog a USING(source_instance_id,producer_id,capture_id)""",
                self._destination,
                self._source,
                lease_seconds,
            )
        return None if raw is None else CaptureDeliveryLease.model_validate_json(raw)

    def _scope(self, lease: CaptureDeliveryLease) -> None:
        if (
            lease.destination_id != self._destination
            or lease.capture.run.source_instance_id != self._source
        ):
            raise ValueError("capture lease belongs to another namespace")

    async def renew(self, lease: CaptureDeliveryLease, lease_seconds: int = 120) -> None:
        self._scope(lease)
        if lease_seconds < 1:
            raise ValueError("capture lease duration must be positive")
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                """UPDATE session_capture_delivery_jobs
                SET leased_until=now()+$6::double precision*interval '1 second'
                WHERE destination_id=$1 AND source_instance_id=$2 AND producer_id=$3 AND capture_id=$4
                AND lease_token=$5 AND leased_until>now() AND NOT cancelled AND NOT queued RETURNING capture_id""",
                self._destination,
                self._source,
                lease.capture.producer_id,
                lease.capture.capture_id,
                lease.token,
                lease_seconds,
            )
        if result is None:
            raise CaptureDeliveryLeaseLost("capture delivery lease expired or superseded")

    async def record_content_hash(self, lease: CaptureDeliveryLease, content_hash: str) -> None:
        """Durably bind the APSS source-content hash before bytes reach the exporter.

        Replica deletion then never depends on local bytes still existing. Fails
        when a tombstone already exists, so a withdrawn body is never enqueued.
        """
        self._scope(lease)
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                """UPDATE session_capture_delivery_jobs j SET content_hash=$6
                WHERE j.destination_id=$1 AND j.source_instance_id=$2 AND j.producer_id=$3
                AND j.capture_id=$4 AND j.lease_token=$5 AND j.leased_until>now()
                AND NOT j.cancelled AND NOT j.queued
                AND NOT EXISTS (SELECT 1 FROM session_body_deletions d
                    WHERE d.source_instance_id=j.source_instance_id AND d.archive_sha256=$7)
                RETURNING capture_id""",
                self._destination,
                self._source,
                lease.capture.producer_id,
                lease.capture.capture_id,
                lease.token,
                content_hash,
                lease.capture.archive.sha256,
            )
        if result is None:
            raise CaptureDeliveryLeaseLost("capture delivery lease expired, superseded or deleted")

    async def drain_blocked(self, conn: Connection) -> bool:
        """Whether a tombstoned body may still sit in this destination's outbox.

        True until the replica has authoritatively acknowledged deletion for every
        capture of a tombstoned object that reached (or may have reached) the
        exporter. Call under the shared deletion fence, on its connection.
        """
        blocked = await conn.fetchval(
            """SELECT EXISTS(
                SELECT 1 FROM session_body_deletions d
                JOIN session_capture_catalog c ON c.source_instance_id=d.source_instance_id
                    AND c.payload->'archive'->>'sha256'=d.archive_sha256
                JOIN session_capture_delivery_jobs j ON j.source_instance_id=c.source_instance_id
                    AND j.producer_id=c.producer_id AND j.capture_id=c.capture_id
                    AND j.destination_id=$2
                WHERE d.source_instance_id=$1 AND (j.queued OR j.content_hash IS NOT NULL)
                AND COALESCE(j.content_hash,d.content_hash) IS NOT NULL
                AND NOT EXISTS(SELECT 1 FROM session_capture_deletion_checkpoints k
                    WHERE k.source_instance_id=c.source_instance_id AND k.destination_id=$2
                    AND k.producer_id=c.producer_id AND k.capture_id=c.capture_id
                    AND k.acknowledged))::text""",
            self._source,
            self._destination,
        )
        return blocked == "true"

    async def finish(
        self, lease: CaptureDeliveryLease, *, queued: bool, retry_seconds: int = 0
    ) -> None:
        self._scope(lease)
        if retry_seconds < 0:
            raise ValueError("capture retry delay must be nonnegative")
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                """UPDATE session_capture_delivery_jobs SET queued=$6,
                leased_until='-infinity',retry_at=now()+$7::double precision*interval '1 second'
                WHERE destination_id=$1 AND source_instance_id=$2 AND producer_id=$3 AND capture_id=$4
                AND lease_token=$5 AND leased_until>now() AND NOT cancelled AND NOT queued RETURNING capture_id""",
                self._destination,
                self._source,
                lease.capture.producer_id,
                lease.capture.capture_id,
                lease.token,
                queued,
                retry_seconds,
            )
        if result is None:
            raise CaptureDeliveryLeaseLost("capture delivery lease expired or superseded")

    async def claim_receipt(self, lease_seconds: int = 120) -> CaptureDeliveryLease | None:
        if lease_seconds < 1:
            raise ValueError("capture receipt lease duration must be positive")
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                """WITH candidate AS (
                    SELECT destination_id,source_instance_id,producer_id,capture_id
                    FROM session_capture_delivery_jobs
                    WHERE destination_id=$1 AND source_instance_id=$2
                    AND NOT cancelled AND queued AND NOT receipt_recorded AND receipt_poll_at<=now()
                    ORDER BY receipt_poll_at,producer_id,capture_id
                    FOR UPDATE SKIP LOCKED LIMIT 1
                ), claimed AS (
                    UPDATE session_capture_delivery_jobs j
                    SET receipt_lease_token=j.receipt_lease_token+1,
                        receipt_poll_at=now()+$3::double precision*interval '1 second'
                    FROM candidate c WHERE j.destination_id=c.destination_id
                    AND j.source_instance_id=c.source_instance_id AND j.producer_id=c.producer_id
                    AND j.capture_id=c.capture_id RETURNING j.*
                ) SELECT jsonb_build_object('capture',a.payload,'destination_id',c.destination_id,
                    'token',c.receipt_lease_token)::text FROM claimed c
                    JOIN session_capture_catalog a USING(source_instance_id,producer_id,capture_id)""",
                self._destination,
                self._source,
                lease_seconds,
            )
        return None if raw is None else CaptureDeliveryLease.model_validate_json(raw)

    async def finish_receipt(
        self, lease: CaptureDeliveryLease, *, recorded: bool, retry_seconds: int = 10
    ) -> None:
        self._scope(lease)
        if retry_seconds < 0:
            raise ValueError("capture receipt retry delay must be nonnegative")
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                """UPDATE session_capture_delivery_jobs SET receipt_recorded=$6,
                    receipt_poll_at=now()+$7::double precision*interval '1 second'
                WHERE destination_id=$1 AND source_instance_id=$2 AND producer_id=$3 AND capture_id=$4
                AND receipt_lease_token=$5 AND receipt_poll_at>now() AND NOT cancelled AND queued
                AND NOT receipt_recorded RETURNING capture_id""",
                self._destination,
                self._source,
                lease.capture.producer_id,
                lease.capture.capture_id,
                lease.token,
                recorded,
                retry_seconds,
            )
        if result is None:
            raise CaptureDeliveryLeaseLost("capture receipt lease expired or superseded")
