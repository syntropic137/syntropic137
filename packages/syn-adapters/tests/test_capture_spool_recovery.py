"""Durable spool cursors fence expired workers and survive replay/restart."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.postgres_spools import PostgresCaptureSpools
from syn_domain.contexts.agent_sessions import CaptureSpool, CaptureSpoolLeaseLost, RunIdentity

if TYPE_CHECKING:
    import asyncpg

pytestmark = pytest.mark.integration


async def test_replay_preserves_cursor_and_expired_worker_cannot_advance(
    db_pool: asyncpg.Pool,
) -> None:
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source_id = str(uuid4())
    spools = PostgresCaptureSpools(db_pool, source_id)
    spool = CaptureSpool(
        run=RunIdentity(source_instance_id=source_id, execution_id="run"),
        session_id="session",
        phase_id="phase",
    )
    await spools.project(spool)
    other_installation = PostgresCaptureSpools(db_pool, str(uuid4()))
    assert await other_installation.claim(lease_seconds=60) is None
    with pytest.raises(ValueError, match="installation"):
        await other_installation.project(spool)
    lease = await spools.claim(lease_seconds=60)
    assert lease is not None
    assert lease.spool == spool
    assert await spools.claim(lease_seconds=60) is None
    await spools.advance(lease, after=5, watermark=10, retry_seconds=0)
    await spools.project(spool)
    restarted = PostgresCaptureSpools(db_pool, source_id)
    next_lease = await restarted.claim(lease_seconds=60)
    assert next_lease is not None
    assert next_lease.after == 5 and next_lease.watermark == 10
    with pytest.raises(CaptureSpoolLeaseLost):
        await spools.advance(lease, after=10, watermark=None, retry_seconds=0)
    with pytest.raises(ValueError, match="incomplete"):
        await restarted.advance(next_lease, after=7, watermark=None, retry_seconds=0)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_capture_spools SET leased_until=now()-interval '1 second' WHERE source_instance_id=$1",
            spool.run.source_instance_id,
        )
    replacement = await restarted.claim(lease_seconds=60)
    assert replacement is not None and replacement.token > next_lease.token
    with pytest.raises(CaptureSpoolLeaseLost):
        await spools.advance(next_lease, after=10, watermark=None, retry_seconds=0)
    await restarted.advance(replacement, after=10, watermark=None, retry_seconds=0)
    await restarted.project(spool)
    final = await restarted.claim(lease_seconds=60)
    assert final is not None and final.after == 10 and final.watermark is None
    with pytest.raises(ValueError, match="rebound"):
        await restarted.project(spool.model_copy(update={"phase_id": "other"}))
