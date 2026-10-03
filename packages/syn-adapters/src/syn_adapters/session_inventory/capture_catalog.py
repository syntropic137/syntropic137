"""Persist archive acquisition metadata before acknowledging local capture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import CataloguedCapture

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import RunIdentity
    from syn_domain.contexts.agent_sessions.ports.QualifiedSessionStorePort import (
        QualifiedSessionIdentity,
    )

if TYPE_CHECKING:
    from .database import Pool


class CaptureCatalogConflict(RuntimeError):
    """A producer reused a capture identity for different acquisition data."""


class PostgresCaptureCatalog:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def record(self, capture: CataloguedCapture) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_capture_catalog
                (source_instance_id,producer_id,capture_id,payload) VALUES($1,$2,$3,$4::jsonb)
                ON CONFLICT(source_instance_id,producer_id,capture_id) DO NOTHING""",
                capture.run.source_instance_id,
                capture.producer_id,
                capture.capture_id,
                capture.model_dump_json(),
            )
            # Separate READ COMMITTED statement sees a concurrent winner after
            # the insert waits. Never mistake a conflicting retry for success.
            raw = await conn.fetchval(
                """SELECT payload::text FROM session_capture_catalog
                WHERE source_instance_id=$1 AND producer_id=$2 AND capture_id=$3""",
                capture.run.source_instance_id,
                capture.producer_id,
                capture.capture_id,
            )
        if raw is None or CataloguedCapture.model_validate_json(raw) != capture:
            raise CaptureCatalogConflict("capture identity conflicts with durable acquisition")

    async def get(
        self, run: RunIdentity, producer_id: str, capture_id: str
    ) -> CataloguedCapture | None:
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                """SELECT payload::text FROM session_capture_catalog
                WHERE source_instance_id=$1 AND producer_id=$2 AND capture_id=$3""",
                run.source_instance_id,
                producer_id,
                capture_id,
            )
        if raw is None:
            return None
        capture = CataloguedCapture.model_validate_json(raw)
        return capture if capture.run == run else None

    async def get_revision(
        self, run: RunIdentity, identity: QualifiedSessionIdentity, archive_hash: str
    ) -> CataloguedCapture | None:
        if identity.source_instance_id != run.source_instance_id:
            return None
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                """SELECT payload::text FROM session_capture_catalog
                WHERE source_instance_id=$1 AND payload->'run'->>'execution_id'=$2
                AND payload->>'harness'=$3 AND payload->>'native_id'=$4
                AND payload->'archive'->>'sha256'=$5
                ORDER BY producer_id,capture_id LIMIT 1""",
                run.source_instance_id,
                run.execution_id,
                identity.harness,
                identity.local_id,
                archive_hash,
            )
        return None if raw is None else CataloguedCapture.model_validate_json(raw)
