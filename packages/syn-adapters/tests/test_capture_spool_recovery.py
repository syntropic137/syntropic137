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
    # Caught up and live: not re-swept until settlement or the live interval (#2107).
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
    assert await restarted.claim(lease_seconds=60) is None
    await restarted.settle("session")
    final = await restarted.claim(lease_seconds=60)
    assert final is not None
    assert (final.after, final.child_after, final.child_watermark) == (50, 5, None)


async def test_caught_up_live_spool_is_reswept_only_on_settlement_or_live_interval(
    db_pool: asyncpg.Pool,
) -> None:
    """#2107: each re-sweep of a live transcript archives a full new revision."""
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    spools = PostgresCaptureSpools(db_pool, source, live_resweep_seconds=600)
    with pytest.raises(ValueError, match="positive"):
        PostgresCaptureSpools(db_pool, source, live_resweep_seconds=0)
    run = RunIdentity(source_instance_id=source, execution_id="run")
    for session in ("envelope", "child", "settled", "aged"):
        await spools.project(CaptureSpool(run=run, session_id=session, phase_id="phase"))

    async def caught_up(session: str) -> None:
        lease = await spools.claim(lease_seconds=60)  # first claims are never gated
        assert lease is not None and lease.spool.session_id == session
        await spools.advance(lease, after=1, watermark=None, retry_seconds=0)

    for session in ("aged", "child", "envelope", "settled"):
        await caught_up(session)
    assert await spools.claim(lease_seconds=60) is None

    # An unfinished traversal is not a re-sweep: it continues at once.
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_capture_spools SET watermark=9
            WHERE source_instance_id=$1 AND session_id='envelope'""",
            source,
        )
        await conn.execute(
            """UPDATE session_capture_spools SET child_watermark=9
            WHERE source_instance_id=$1 AND session_id='child'""",
            source,
        )
        await conn.execute(
            """UPDATE session_capture_spools SET claimed_at=now()-interval '601 seconds'
            WHERE source_instance_id=$1 AND session_id='aged'""",
            source,
        )
    await spools.settle("settled")
    claimed = set()
    while (lease := await spools.claim(lease_seconds=60)) is not None:
        claimed.add(lease.spool.session_id)
    assert claimed == {"envelope", "child", "settled", "aged"}
