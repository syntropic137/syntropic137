"""Durable spool cursors fence expired workers and survive replay/restart."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.postgres_spools import PostgresCaptureSpools
from syn_domain.contexts.agent_sessions import (
    CaptureSpool,
    CaptureSpoolLease,
    CaptureSpoolLeaseLost,
    RunIdentity,
)

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
    await restarted.mark_drained(replacement)
    # Fully traversed and live: not re-swept until settlement or the live interval (#2107).
    assert await restarted.claim(lease_seconds=60) is None
    await restarted.settle("session")
    final = await restarted.claim(lease_seconds=60)
    assert final is not None and final.after == 10 and final.watermark is None
    with pytest.raises(ValueError, match="rebound"):
        await restarted.project(spool.model_copy(update={"phase_id": "other"}))


async def test_child_cursor_is_independent_restart_safe_and_fenced(db_pool: asyncpg.Pool) -> None:
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    spools = PostgresCaptureSpools(db_pool, source)
    spool = CaptureSpool(
        run=RunIdentity(source_instance_id=source, execution_id="run"),
        session_id="session",
        phase_id="phase",
    )
    await spools.project(spool)
    lease = await spools.claim(lease_seconds=60)
    assert lease is not None
    assert lease.child_after == 0 and lease.child_watermark is None
    await spools.advance_children(lease, after=2, watermark=5)
    # Advancing child work neither releases the lease nor changes envelope progress.
    assert await spools.claim(lease_seconds=60) is None
    with pytest.raises(CaptureSpoolLeaseLost):
        await spools.advance_children(lease, after=1, watermark=5)
    await spools.advance(lease, after=40, watermark=50, retry_seconds=0)
    restarted = PostgresCaptureSpools(db_pool, source)
    current = await restarted.claim(lease_seconds=60)
    assert current is not None
    assert (current.after, current.watermark) == (40, 50)
    assert (current.child_after, current.child_watermark) == (2, 5)
    with pytest.raises(ValueError, match="incomplete"):
        await restarted.advance_children(current, after=3, watermark=None)
    with pytest.raises(ValueError, match="watermark"):
        await restarted.advance_children(current, after=3, watermark=6)
    with pytest.raises(CaptureSpoolLeaseLost):
        await spools.advance_children(lease, after=5, watermark=None)
    await restarted.advance_children(current, after=5, watermark=None)
    await restarted.advance(current, after=50, watermark=None, retry_seconds=0)
    await restarted.mark_drained(current)
    assert await restarted.claim(lease_seconds=60) is None
    await restarted.settle("session")
    final = await restarted.claim(lease_seconds=60)
    assert final is not None
    assert (final.after, final.child_after, final.child_watermark) == (50, 5, None)


async def test_live_spool_is_reswept_only_on_settlement_or_live_interval(
    db_pool: asyncpg.Pool,
) -> None:
    """#2107: each re-sweep of a live transcript archives a full new revision.

    Only a complete traversal (``mark_drained``) starts the live cooldown; a
    failed, partial or abandoned one stays due at its retry or lease expiry."""
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    spools = PostgresCaptureSpools(db_pool, source, live_resweep_seconds=600)
    with pytest.raises(ValueError, match="positive"):
        PostgresCaptureSpools(db_pool, source, live_resweep_seconds=0)
    run = RunIdentity(source_instance_id=source, execution_id="run")
    sessions = ("aged", "settled", "failed", "partial", "child_failed", "abandoned")
    for session in sessions:
        await spools.project(CaptureSpool(run=run, session_id=session, phase_id="phase"))

    leases: dict[str, CaptureSpoolLease] = {}
    while (lease := await spools.claim(lease_seconds=60)) is not None:
        leases[lease.spool.session_id] = lease
    assert set(leases) == set(sessions)  # never traversed: all due at once
    for session in ("aged", "settled"):
        await spools.advance(leases[session], after=1, watermark=None, retry_seconds=0)
        await spools.mark_drained(leases[session])
    # The worker's failure path: cursors kept, retried after retry_seconds.
    await spools.advance(leases["failed"], after=0, watermark=None, retry_seconds=0)
    await spools.advance(leases["partial"], after=1, watermark=9, retry_seconds=0)
    # Transcript complete, child journal failed: never marked drained.
    await spools.advance(leases["child_failed"], after=1, watermark=None, retry_seconds=0)
    # "abandoned": the process died holding the lease; it expires below.
    assert {lease.spool.session_id for lease in await _claim_all(spools)} == {
        "failed",
        "partial",
        "child_failed",
    }
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_capture_spools SET leased_until=now()-interval '1 second'
            WHERE source_instance_id=$1""",
            source,
        )
    assert {lease.spool.session_id for lease in await _claim_all(spools)} == {
        "failed",
        "partial",
        "child_failed",
        "abandoned",
    }
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_capture_spools SET leased_until=now()-interval '1 second'
            WHERE source_instance_id=$1""",
            source,
        )
        await conn.execute(
            """UPDATE session_capture_spools SET drained_at=drained_at-interval '601 seconds'
            WHERE source_instance_id=$1 AND session_id='aged'""",
            source,
        )
    await spools.settle("settled")
    assert {lease.spool.session_id for lease in await _claim_all(spools)} == set(sessions)


async def _claim_all(spools: PostgresCaptureSpools) -> list[CaptureSpoolLease]:
    leases: list[CaptureSpoolLease] = []
    while (lease := await spools.claim(lease_seconds=60)) is not None:
        leases.append(lease)
    return leases
