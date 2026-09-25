"""Fenced local transfer from the capture catalog to the exporter's durable queue."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.agent_sessions import CataloguedCapture  # noqa: TC001

if TYPE_CHECKING:
    from .database import Connection, Pool


class CaptureDeliveryLeaseLost(RuntimeError):
    pass


class DrainTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    producer_id: str
    capture_id: str
    withdrawn: bool
    """Tombstoned or cancelled: the outbox is discarded, never sent."""


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

    async def withdrawn(self, capture: CataloguedCapture) -> bool:
        """Current tombstone or cancellation for this capture's exact bytes."""
        async with self._pool.acquire() as conn:
            found = await conn.fetchval(
                """SELECT (EXISTS(SELECT 1 FROM session_body_deletions d
                    WHERE d.source_instance_id=$2 AND d.archive_sha256=$5)
                OR EXISTS(SELECT 1 FROM session_capture_delivery_jobs j
                    WHERE j.destination_id=$1 AND j.source_instance_id=$2
                    AND j.producer_id=$3 AND j.capture_id=$4 AND j.cancelled))::text""",
                self._destination,
                self._source,
                capture.producer_id,
                capture.capture_id,
                capture.archive.sha256,
            )
        return found == "true"

    async def claim_drain(self, lease_seconds: int = 120) -> DrainTarget | None:
        """One capture whose own outbox may still hold a queued upload.

        Cancelled jobs are included: their outbox must be discarded, not sent.
        Call under the shared deletion fence so ``withdrawn`` cannot go stale.
        """
        if lease_seconds < 1:
            raise ValueError("capture drain lease must be positive")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """WITH candidate AS (
                    SELECT destination_id,source_instance_id,producer_id,capture_id
                    FROM session_capture_delivery_jobs
                    WHERE destination_id=$1 AND source_instance_id=$2
                    AND queued AND NOT outbox_drained AND drain_at<=now()
                    ORDER BY drain_at,producer_id,capture_id FOR UPDATE SKIP LOCKED LIMIT 1
                ), claimed AS (
                    UPDATE session_capture_delivery_jobs j
                    SET drain_at=now()+$3::double precision*interval '1 second'
                    FROM candidate c WHERE j.destination_id=c.destination_id
                    AND j.source_instance_id=c.source_instance_id
                    AND j.producer_id=c.producer_id AND j.capture_id=c.capture_id
                    RETURNING j.producer_id,j.capture_id,j.cancelled
                )
                SELECT c.producer_id,c.capture_id,
                (c.cancelled OR EXISTS(SELECT 1 FROM session_body_deletions d
                    WHERE d.source_instance_id=$2
                    AND d.archive_sha256=a.payload->'archive'->>'sha256'))::text AS withdrawn
                FROM claimed c JOIN session_capture_catalog a
                ON a.source_instance_id=$2 AND a.producer_id=c.producer_id
                AND a.capture_id=c.capture_id""",
                self._destination,
                self._source,
                lease_seconds,
            )
        if not rows:
            return None
        row = rows[0]
        return DrainTarget(
            producer_id=row["producer_id"],
            capture_id=row["capture_id"],
            withdrawn=row["withdrawn"] == "true",
        )

    async def finish_drain(
        self, target: DrainTarget, *, drained: bool, retry_seconds: int = 0
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE session_capture_delivery_jobs
                SET outbox_drained=$5,
                drain_at=CASE WHEN $5 THEN drain_at
                    ELSE now()+$6::double precision*interval '1 second' END
                WHERE destination_id=$1 AND source_instance_id=$2
                AND producer_id=$3 AND capture_id=$4""",
                self._destination,
                self._source,
                target.producer_id,
                target.capture_id,
                drained,
                retry_seconds,
            )

    async def reset_legacy_queue(self, conn: Connection) -> bool:
        """Once per destination: captures queued in the retired shared outbox.

        Undelivered, non-withdrawn captures are redelivered through their own
        outboxes; everything else is marked drained because that outbox is gone.
        Returns whether this call performed the reset. Run under the exclusive
        fence, in a transaction on ``conn``.
        """
        created = await conn.fetchval(
            """INSERT INTO session_capture_outbox_retirements(source_instance_id,destination_id)
            VALUES ($1,$2) ON CONFLICT DO NOTHING RETURNING destination_id""",
            self._source,
            self._destination,
        )
        if created is None:
            return False
        await conn.execute(
            """UPDATE session_capture_delivery_jobs SET
            queued=CASE WHEN NOT cancelled AND NOT receipt_recorded THEN FALSE ELSE queued END,
            outbox_drained=(cancelled OR receipt_recorded),
            retry_at='-infinity',leased_until='-infinity'
            WHERE destination_id=$1 AND source_instance_id=$2 AND queued
            AND NOT outbox_drained""",
            self._destination,
            self._source,
        )
        return True

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
