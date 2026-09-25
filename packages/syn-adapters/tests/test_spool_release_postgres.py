"""Row 11 (#1398): staged spool bytes leave only after archive ack or recorded expiry.

Real PostgreSQL spool rows and evidence journal; the volume port is a double so
in-use and removal outcomes are explicit. Release is two-phase and restart safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.postgres_spools import PostgresCaptureSpools
from syn_adapters.session_inventory.spool_release import (
    SPOOL_EXPIRED_GAP,
    CaptureSpoolRetention,
    expiry_gap,
)
from syn_domain.contexts.agent_sessions import CaptureSpool, CaptureSpoolLease, RunIdentity

if TYPE_CHECKING:
    import asyncpg

pytestmark = pytest.mark.integration


class Volumes:
    def __init__(self) -> None:
        self.in_use: set[str] = set()
        self.removed: list[str] = []
        self.present: set[str] = set()

    async def remove(self, spool: CaptureSpool) -> bool:
        if spool.session_id in self.in_use:
            return False
        self.removed.append(spool.session_id)
        self.present.discard(spool.session_id)
        return True


async def _setup(
    pool: asyncpg.Pool, **policy: int | None
) -> tuple[PostgresCaptureSpools, CaptureSpoolRetention, Volumes, PostgresSessionEvidence, str]:
    evidence = PostgresSessionEvidence(pool)
    await evidence.ensure_ready()
    source = str(uuid4())
    spools = PostgresCaptureSpools(pool, source)
    volumes = Volumes()
    grace = policy.pop("settle_grace_seconds", None) or 3600
    retention = CaptureSpoolRetention(
        pool,
        source,
        volumes,
        evidence,
        settle_grace_seconds=grace,
        age_seconds=policy.get("age_seconds"),
        max_bytes=policy.get("max_bytes"),
    )
    return spools, retention, volumes, evidence, source


def _spool(source: str, session: str) -> CaptureSpool:
    return CaptureSpool(
        run=RunIdentity(source_instance_id=source, execution_id="run"),
        session_id=session,
        phase_id="phase",
    )


async def _traverse(spools: PostgresCaptureSpools, *, staged: int = 0) -> CaptureSpoolLease:
    lease = await spools.claim(lease_seconds=60)
    assert lease is not None
    await spools.advance(lease, after=0, watermark=None, retry_seconds=0, staged_bytes=staged)
    await spools.mark_drained(lease)
    return lease


async def _gaps(pool: asyncpg.Pool, source: str) -> int:
    async with pool.acquire() as conn:
        return int(
            await conn.fetchval(
                """SELECT count(*) FROM session_evidence_batches
                WHERE source_instance_id=$1 AND producer_id='capture-spool-retention'""",
                source,
            )
        )


async def test_archived_release_requires_settlement_later_traversal_and_exclusivity(
    db_pool: asyncpg.Pool,
) -> None:
    spools, retention, volumes, _, source = await _setup(db_pool)
    await spools.project(_spool(source, "s"))
    early = await _traverse(spools, staged=512)
    # Unsettled and inside the grace period: a workspace may not have started yet.
    assert not await retention.after_drain(early, exclusive=True)
    await spools.settle("s")
    await spools.settle("s")  # replay-safe
    # The traversal began before settlement, so it proves nothing about final bytes.
    assert not await retention.after_drain(early, exclusive=True)
    later = await _traverse(spools)
    assert not await retention.after_drain(later, exclusive=False)
    assert await retention.after_drain(later, exclusive=True)
    assert volumes.removed == ["s"]
    assert await spools.claim(lease_seconds=60) is None  # never drained again
    assert await retention.step() == 0  # nothing pending, nothing repeated
    assert await _gaps(db_pool, source) == 0  # archived releases record no gap
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT release_reason,released_at IS NOT NULL AS released,staged_bytes
            FROM session_capture_spools WHERE source_instance_id=$1""",
            source,
        )
    assert row is not None and row["release_reason"] == "archived" and row["released"]
    assert row["staged_bytes"] == 512


async def test_in_use_volume_reopens_an_archived_release_for_capture(
    db_pool: asyncpg.Pool,
) -> None:
    spools, retention, volumes, _, source = await _setup(db_pool)
    await spools.project(_spool(source, "s"))
    await spools.settle("s")
    volumes.in_use.add("s")
    lease = await _traverse(spools)
    assert not await retention.after_drain(lease, exclusive=True)
    # A container attached after traversal; its writes are not archived yet.
    again = await spools.claim(lease_seconds=60)
    assert again is not None and again.token > lease.token


async def test_unsettled_spool_releases_after_grace_when_fully_archived(
    db_pool: asyncpg.Pool,
) -> None:
    spools, retention, volumes, _, source = await _setup(db_pool, settle_grace_seconds=60)
    await spools.project(_spool(source, "legacy"))
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_capture_spools SET registered_at=now()-interval '2 minutes'
            WHERE source_instance_id=$1""",
            source,
        )
    assert await retention.after_drain(await _traverse(spools), exclusive=True)
    assert volumes.removed == ["legacy"]


async def test_expiry_records_gap_before_removal_and_retries_until_removed(
    db_pool: asyncpg.Pool,
) -> None:
    spools, retention, volumes, evidence, source = await _setup(db_pool, age_seconds=3600)
    spool = _spool(source, "stale")
    await spools.project(spool)
    await spools.project(_spool(source, "fresh"))
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_capture_spools SET registered_at=now()-interval '2 hours'
            WHERE source_instance_id=$1 AND session_id='stale'""",
            source,
        )
    volumes.in_use.add("stale")
    assert await retention.step() == 0
    # Gap first: discoverable absence exists even while bytes are still retained.
    assert await _gaps(db_pool, source) == 1
    page = await evidence.read(spool.run, await evidence.watermark(spool.run))
    gap = page.items[-1].batch.evidence.acquisition_gaps[0].gap
    assert gap.reason == SPOOL_EXPIRED_GAP and gap.node_keys
    assert await spools.claim(lease_seconds=60) is not None  # fresh spool only
    volumes.in_use.clear()
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_capture_spools SET leased_until='-infinity' WHERE source_instance_id=$1",
            source,
        )
    assert await retention.step() == 1
    assert volumes.removed == ["stale"]
    assert await retention.step() == 0
    assert await _gaps(db_pool, source) == 1  # idempotent journal batch
    assert expiry_gap(spool) == expiry_gap(spool)


async def test_byte_quota_expires_oldest_settled_spool_never_live_capture(
    db_pool: asyncpg.Pool,
) -> None:
    spools, retention, volumes, _, source = await _setup(db_pool, max_bytes=1000)
    for index, name in enumerate(("live-oldest", "settled-old", "settled-new")):
        await spools.project(_spool(source, name))
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE session_capture_spools
                SET registered_at=now()-$3::double precision*interval '1 minute',staged_bytes=600
                WHERE source_instance_id=$1 AND session_id=$2""",
                source,
                name,
                10 - index,
            )
    await spools.settle("settled-old")
    await spools.settle("settled-new")
    assert await retention.step() == 1
    # 1800 retained bytes: the live session is oldest but must never be evicted.
    assert volumes.removed == ["settled-old"]
    assert await retention.step() == 0
    assert volumes.removed == ["settled-old"]


async def test_settle_and_release_are_scoped_to_one_installation(db_pool: asyncpg.Pool) -> None:
    spools, retention, volumes, _, source = await _setup(db_pool)
    await spools.project(_spool(source, "shared-name"))
    other_spools, other_retention, _, _, other = await _setup(db_pool)
    await other_spools.project(_spool(other, "shared-name"))
    await other_spools.settle("shared-name")
    lease = await _traverse(spools)
    assert not await retention.after_drain(lease, exclusive=True)
    assert volumes.removed == []
    foreign = lease.model_copy(update={"spool": _spool(other, "shared-name")})
    assert not await retention.after_drain(foreign, exclusive=True)
    assert not await other_retention.after_drain(lease, exclusive=True)
