"""Real SQL tests: crash boundaries, fencing, and snapshot-pinned reads (#1398)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.postgres_inventory import PostgresSessionInventory
from syn_domain.contexts.agent_sessions import (
    InventoryCounts,
    InventoryCoverage,
    InventoryNamespaceCount,
    InventoryNode,
    InventoryNotFound,
    InventoryPublicationConflict,
    InventorySnapshot,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    CoverageState,
    InventoryNodeRef,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    import asyncpg

pytestmark = pytest.mark.integration


async def test_capture_delivery_jobs_fence_expired_workers_and_separate_destinations(
    db_pool: asyncpg.Pool,
    inventory: PostgresSessionInventory,
) -> None:
    from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
    from syn_adapters.session_inventory.capture_delivery_jobs import (
        CaptureDeliveryLeaseLost,
        PostgresCaptureDeliveryJobs,
    )
    from syn_domain.contexts.agent_sessions import CataloguedCapture
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
        ArchivedTranscript,
    )

    source = str(uuid4())
    capture = CataloguedCapture(
        run=RunIdentity(source_instance_id=source, execution_id="run"),
        producer_id="spool",
        capture_id="one",
        harness="codex",
        native_id="native",
        content_format="envelope",
        archive=ArchivedTranscript(sha256="a" * 64, size=42),
    )
    catalog = PostgresCaptureCatalog(db_pool)
    await catalog.record(capture)
    await catalog.record(capture.model_copy(update={"capture_id": "unknown", "native_id": None}))
    await catalog.record(
        capture.model_copy(update={"capture_id": "native-only", "content_format": "native"})
    )
    jobs = PostgresCaptureDeliveryJobs(db_pool, source, "store-a")
    await jobs.discover()
    claims = await asyncio.gather(jobs.claim(), jobs.claim())
    claimed = [lease for lease in claims if lease is not None]
    assert len(claimed) == 1
    first = claimed[0]
    assert first.capture == capture
    await jobs.renew(first)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_capture_delivery_jobs SET leased_until=now()-interval '1 second' WHERE source_instance_id=$1",
            source,
        )
    restarted = PostgresCaptureDeliveryJobs(db_pool, source, "store-a")
    second = await restarted.claim()
    assert second is not None and second.token > first.token
    with pytest.raises(CaptureDeliveryLeaseLost):
        await jobs.finish(first, queued=True)
    with pytest.raises(CaptureDeliveryLeaseLost):
        await jobs.renew(first)
    other = PostgresCaptureDeliveryJobs(db_pool, source, "store-b")
    with pytest.raises(ValueError, match="namespace"):
        await other.finish(second, queued=True)
    await restarted.finish(second, queued=False)
    retried = await restarted.claim()
    assert retried is not None
    await restarted.finish(retried, queued=True)
    await restarted.discover()
    assert await restarted.claim() is None
    await other.discover()
    assert await other.claim() is not None
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM session_capture_delivery_jobs WHERE source_instance_id=$1", source
        )
        await conn.execute(
            "DELETE FROM session_capture_catalog WHERE source_instance_id=$1", source
        )


async def test_capture_catalog_survives_retry_and_rejects_changed_identity(
    db_pool: asyncpg.Pool,
    inventory: PostgresSessionInventory,
) -> None:
    from syn_adapters.session_inventory.capture_catalog import (
        CaptureCatalogConflict,
        PostgresCaptureCatalog,
    )
    from syn_domain.contexts.agent_sessions import CataloguedCapture
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
        ArchivedTranscript,
    )

    record = CataloguedCapture(
        run=RunIdentity(source_instance_id=str(uuid4()), execution_id="run"),
        producer_id="spool",
        capture_id="capture",
        harness="codex",
        native_id=None,
        content_format="envelope",
        archive=ArchivedTranscript(sha256="a" * 64, size=42),
    )
    from syn_domain.contexts.agent_sessions.ports.QualifiedSessionStorePort import (
        QualifiedSessionIdentity,
    )

    record = record.model_copy(update={"native_id": "opaque/雪"})
    identity = QualifiedSessionIdentity(
        kind="transcript",
        source_instance_id=record.run.source_instance_id,
        harness="codex",
        local_id="opaque/雪",
    )
    catalog = PostgresCaptureCatalog(db_pool)
    await asyncio.gather(catalog.record(record), PostgresCaptureCatalog(db_pool).record(record))
    assert await catalog.get(record.run, "spool", "capture") == record
    assert await catalog.get(record.run, "spool", "absent") is None
    assert (
        await catalog.get(
            record.run.model_copy(update={"execution_id": "other-run"}), "spool", "capture"
        )
        is None
    )
    assert (
        await catalog.get(
            record.run.model_copy(update={"source_instance_id": "other-source"}), "spool", "capture"
        )
        is None
    )
    newer = record.model_copy(
        update={"capture_id": "newer", "archive": ArchivedTranscript(sha256="b" * 64, size=43)}
    )
    await catalog.record(newer)
    assert await catalog.get_revision(record.run, identity, record.archive.sha256) == record
    assert await catalog.get_revision(record.run, identity, newer.archive.sha256) == newer
    assert await catalog.get_revision(record.run, identity, "c" * 64) is None
    assert (
        await catalog.get_revision(
            record.run, identity.model_copy(update={"harness": "claude"}), record.archive.sha256
        )
        is None
    )
    assert (
        await catalog.get_revision(
            record.run.model_copy(update={"execution_id": "other"}), identity, record.archive.sha256
        )
        is None
    )
    assert (
        await catalog.get_revision(
            record.run,
            identity.model_copy(update={"source_instance_id": "other"}),
            record.archive.sha256,
        )
        is None
    )
    with pytest.raises(CaptureCatalogConflict):
        await catalog.record(record.model_copy(update={"content_format": "native"}))
    async with db_pool.acquire() as connection:
        raw = await connection.fetchval(
            "SELECT payload::text FROM session_capture_catalog WHERE source_instance_id=$1 AND capture_id='capture'",
            record.run.source_instance_id,
        )
        assert CataloguedCapture.model_validate_json(raw) == record
        await connection.execute(
            "DELETE FROM session_capture_catalog WHERE source_instance_id=$1",
            record.run.source_instance_id,
        )


@pytest.fixture
async def inventory(db_pool: asyncpg.Pool) -> AsyncIterator[PostgresSessionInventory]:
    store = PostgresSessionInventory(db_pool)
    await store.ensure_ready()
    yield store


def snapshot(run: RunIdentity, count: int = 3, watermark: int = 1) -> InventorySnapshot:
    return InventorySnapshot(
        snapshot_id=uuid4(),
        run=run,
        revision=f"revision-{watermark}",
        resolver_version="test/1",
        evidence_watermark=watermark,
        coverage=InventoryCoverage(state=CoverageState.UNKNOWN),
        counts=InventoryCounts(
            node=count,
            membership=0,
            edge=0,
            capture=0,
            gap=0,
            # What the current build derives from nodes(); legacy shape via without_derived_counts().
            namespaces=(
                (InventoryNamespaceCount(kind="transcript", harness="third-harness", count=count),)
                if count
                else ()
            ),
        ),
    )


def nodes(run: RunIdentity, count: int) -> tuple[InventoryNode, ...]:
    return tuple(
        InventoryNode(
            ref=InventoryNodeRef(
                kind="transcript",
                source_instance_id=run.source_instance_id,
                harness="third-harness",
                local_id=str(n),
            )
        )
        for n in range(count)
    )


@pytest.fixture
def run() -> RunIdentity:
    # Unique namespaces let these tests share a database without touching other data.
    return RunIdentity(source_instance_id=f"test-{uuid4()}", execution_id="same-local-run-id")


async def ready(store: PostgresSessionInventory, item: InventorySnapshot) -> None:
    await store.stage(item)
    values = nodes(item.run, item.counts.node)
    for start in range(0, len(values), 500):
        await store.append(item.run, item.snapshot_id, "node", start, values[start : start + 500])


async def test_crash_before_publication_preserves_head_and_retry_is_idempotent(
    inventory: PostgresSessionInventory,
    db_pool: asyncpg.Pool,
    run: RunIdentity,
) -> None:
    old = snapshot(run)
    await ready(inventory, old)
    await inventory.publish(run, old.snapshot_id, None)
    new = snapshot(run, watermark=2)
    await inventory.stage(new)
    await inventory.append(run, new.snapshot_id, "node", 0, nodes(run, 1))
    assert await inventory.head(run) == old
    with pytest.raises(InventoryNotFound):
        await inventory.page(run, new.snapshot_id, "node")
    # Drop every pooled connection and all adapter-local state.
    await db_pool.expire_connections()
    restarted = PostgresSessionInventory(db_pool)
    await ready(restarted, new)
    await restarted.publish(run, new.snapshot_id, old.snapshot_id)
    await restarted.publish(run, new.snapshot_id, old.snapshot_id)
    assert await restarted.head(run) == new


async def test_incomplete_publication_rolls_back_without_hiding_prior_revision(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
) -> None:
    old = snapshot(run)
    await ready(inventory, old)
    await inventory.publish(run, old.snapshot_id, None)
    new = snapshot(run, watermark=2)
    await inventory.stage(new)
    with pytest.raises(InventoryPublicationConflict, match="batches"):
        await inventory.publish(run, new.snapshot_id, old.snapshot_id)
    assert await inventory.head(run) == old
    assert len((await inventory.page(run, old.snapshot_id, "node")).items) == 3


async def test_concurrent_workers_cannot_both_publish_from_same_head(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
) -> None:
    first, second = snapshot(run), snapshot(run)
    await ready(inventory, first)
    await ready(inventory, second)
    results = await asyncio.gather(
        inventory.publish(run, first.snapshot_id, None),
        inventory.publish(run, second.snapshot_id, None),
        return_exceptions=True,
    )
    assert results.count(None) == 1
    assert sum(isinstance(r, InventoryPublicationConflict) for r in results) == 1
    assert await inventory.head(run) in (first, second)


async def test_pagination_stays_on_prior_snapshot_during_concurrent_publication(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
) -> None:
    old = snapshot(run, count=503)
    await ready(inventory, old)
    await inventory.publish(run, old.snapshot_id, None)
    first = await inventory.page(run, old.snapshot_id, "node", limit=500)
    assert len(first.items) == 500
    assert first.next_after == 499
    new = snapshot(run, count=1, watermark=2)
    await ready(inventory, new)
    await inventory.publish(run, new.snapshot_id, old.snapshot_id)
    second = await inventory.page(run, old.snapshot_id, "node", after=first.next_after, limit=500)
    assert second.snapshot == old
    assert len(second.items) == 3
    assert second.next_after is None
    assert first.items + second.items == nodes(run, 503)


async def test_cross_source_and_cross_run_snapshot_reads_fail(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
) -> None:
    item = snapshot(run)
    await ready(inventory, item)
    await inventory.publish(run, item.snapshot_id, None)
    for foreign in (
        run.model_copy(update={"source_instance_id": "other-source"}),
        run.model_copy(update={"execution_id": "other-run"}),
    ):
        assert await inventory.head(foreign) is None
        with pytest.raises(InventoryNotFound):
            await inventory.page(foreign, item.snapshot_id, "node")


async def test_immutable_stage_positions_and_snapshot_metadata(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
) -> None:
    item = snapshot(run)
    await ready(inventory, item)
    await ready(inventory, item)
    with pytest.raises(InventoryPublicationConflict, match="metadata"):
        await inventory.stage(item.model_copy(update={"revision": "changed"}))
    replacement = nodes(run, 4)[-1:]
    with pytest.raises(InventoryPublicationConflict, match="item changed"):
        await inventory.append(run, item.snapshot_id, "node", 0, replacement)
    await inventory.publish(run, item.snapshot_id, None)
    with pytest.raises(InventoryPublicationConflict):
        await inventory.append(run, item.snapshot_id, "node", 0, replacement)
    assert (await inventory.page(run, item.snapshot_id, "node")).items == nodes(run, 3)


async def test_even_current_head_token_cannot_publish_older_evidence(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
) -> None:
    newer, stale = snapshot(run, watermark=5), snapshot(run, watermark=4)
    await ready(inventory, newer)
    await inventory.publish(run, newer.snapshot_id, None)
    await ready(inventory, stale)
    with pytest.raises(InventoryPublicationConflict, match="predates"):
        await inventory.publish(run, stale.snapshot_id, newer.snapshot_id)
    assert await inventory.head(run) == newer


async def test_sparse_or_oversized_batches_cannot_publish_a_truncated_inventory(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
) -> None:
    item = snapshot(run)
    await inventory.stage(item)
    with pytest.raises(ValueError, match="exceeds"):
        await inventory.append(run, item.snapshot_id, "node", 3, nodes(run, 1))
    await inventory.append(run, item.snapshot_id, "node", 2, nodes(run, 1))
    with pytest.raises(InventoryPublicationConflict):
        await inventory.publish(run, item.snapshot_id, None)
    assert await inventory.head(run) is None


async def test_publication_order_is_atomic_durable_and_namespace_scoped(
    inventory: PostgresSessionInventory,
    db_pool: asyncpg.Pool,
    run: RunIdentity,
) -> None:
    from syn_adapters.session_inventory.publications import PostgresInventoryPublications

    publications = PostgresInventoryPublications(db_pool)
    first = snapshot(run, count=1)
    await ready(inventory, first)
    assert await publications.page(run) == ()
    await inventory.publish(run, first.snapshot_id, None)
    await inventory.publish(run, first.snapshot_id, None)
    initial = await publications.page(run, limit=1)
    assert len(initial) == 1
    assert initial[0].snapshot == first
    assert initial[0].revision_sequence == 1
    assert initial[0].first_record_sequence == 1
    assert initial[0].record_high_watermark == 1
    assert initial[0].parent_snapshot_id is None

    second = snapshot(run, count=2, watermark=2)
    await inventory.stage(second)
    with pytest.raises(InventoryPublicationConflict):
        await inventory.publish(run, second.snapshot_id, first.snapshot_id)
    assert await publications.page(run) == initial
    await ready(inventory, second)
    await inventory.publish(run, second.snapshot_id, first.snapshot_id)
    await db_pool.expire_connections()
    restarted = PostgresInventoryPublications(db_pool)
    later = await restarted.page(run, after=1, limit=1)
    assert len(later) == 1
    assert later[0].snapshot == second
    assert later[0].parent_snapshot_id == first.snapshot_id
    assert later[0].revision_sequence == 2
    assert later[0].first_record_sequence == 2
    assert later[0].record_high_watermark == 3
    assert await restarted.page(run, after=2) == ()
    other = RunIdentity(source_instance_id=f"test-{uuid4()}", execution_id=run.execution_id)
    assert await restarted.page(other) == ()
    for after, limit in ((-1, 1), (0, 0), (0, 501)):
        with pytest.raises(ValueError):
            await restarted.page(run, after=after, limit=limit)


async def test_competing_publications_allocate_one_sequence(
    inventory: PostgresSessionInventory,
    db_pool: asyncpg.Pool,
    run: RunIdentity,
) -> None:
    from syn_adapters.session_inventory.publications import PostgresInventoryPublications

    a, b = snapshot(run, count=1), snapshot(run, count=1)
    await ready(inventory, a)
    await ready(inventory, b)
    outcomes = await asyncio.gather(
        inventory.publish(run, a.snapshot_id, None),
        inventory.publish(run, b.snapshot_id, None),
        return_exceptions=True,
    )
    assert sum(outcome is None for outcome in outcomes) == 1
    assert sum(isinstance(outcome, InventoryPublicationConflict) for outcome in outcomes) == 1
    entries = await PostgresInventoryPublications(db_pool).page(run)
    assert len(entries) == 1
    assert entries[0].revision_sequence == 1
    assert entries[0].snapshot == await inventory.head(run)


async def test_record_sequences_are_disjoint_across_runs_and_empty_snapshots(
    inventory: PostgresSessionInventory,
    db_pool: asyncpg.Pool,
    run: RunIdentity,
) -> None:
    from syn_adapters.session_inventory.publications import PostgresInventoryPublications

    other = RunIdentity(source_instance_id=run.source_instance_id, execution_id="other-run")
    first, second = snapshot(run, count=2), snapshot(other, count=3)
    await ready(inventory, first)
    await ready(inventory, second)
    await asyncio.gather(
        inventory.publish(run, first.snapshot_id, None),
        inventory.publish(other, second.snapshot_id, None),
    )
    publications = PostgresInventoryPublications(db_pool)
    (a,) = await publications.page(run)
    (b,) = await publications.page(other)
    ranges = sorted((item.first_record_sequence, item.record_high_watermark) for item in (a, b))
    assert ranges[0][0] == 1
    assert ranges[1][0] == ranges[0][1] + 1
    assert ranges[1][1] == 5
    empty = snapshot(run, count=0, watermark=2)
    await ready(inventory, empty)
    await inventory.publish(run, empty.snapshot_id, first.snapshot_id)
    (c,) = await publications.page(run, after=1)
    assert c.first_record_sequence == 6
    assert c.record_high_watermark == 5


async def test_replication_checkpoint_survives_restart_and_fences_stale_worker(
    inventory: PostgresSessionInventory,
    db_pool: asyncpg.Pool,
    run: RunIdentity,
) -> None:
    from syn_adapters.session_inventory.replication_jobs import (
        PostgresReplicationJobs,
        ReplicationLeaseLost,
    )

    local = snapshot(run, count=2)
    await ready(inventory, local)
    jobs = PostgresReplicationJobs(db_pool, run.source_instance_id, "destination")
    await jobs.discover()
    assert await jobs.claim() is None
    await inventory.publish(run, local.snapshot_id, None)
    await jobs.discover()
    await jobs.discover()
    first = await jobs.claim()
    assert first is not None and first.offset == 0
    assert await jobs.claim() is None
    await jobs.advance(first, next_offset=1)
    restarted = PostgresReplicationJobs(db_pool, run.source_instance_id, "destination")
    second = await restarted.claim()
    assert second is not None and second.offset == 1 and second.token > first.token
    with pytest.raises(ReplicationLeaseLost):
        await jobs.advance(first, next_offset=2)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_inventory_replication_jobs SET leased_until='-infinity' WHERE source_instance_id=$1",
            run.source_instance_id,
        )
    third = await restarted.claim()
    assert third is not None and third.offset == 1
    with pytest.raises(ReplicationLeaseLost):
        await restarted.renew(second)
    await restarted.renew(third)
    await restarted.advance(third, next_offset=None)
    await restarted.discover()
    assert await restarted.claim() is None
    other = PostgresReplicationJobs(db_pool, run.source_instance_id, "another-destination")
    await other.discover()
    separate = await other.claim()
    assert separate is not None and separate.offset == 0
    with pytest.raises(ValueError):
        await other.advance(third, next_offset=None)
    assert await inventory.head(run) == local


async def test_transcript_revocation_survives_restart_and_applies_to_shared_bytes(
    db_pool: asyncpg.Pool, inventory: PostgresSessionInventory
) -> None:
    from syn_adapters.session_inventory.transcript_access import InstallationTranscriptAccess
    from syn_domain.contexts.agent_sessions import ArchivedTranscript, CataloguedCapture

    source = str(uuid4())
    capture = CataloguedCapture(
        run=RunIdentity(source_instance_id=source, execution_id="first"),
        producer_id="producer",
        capture_id="capture",
        harness="codex",
        native_id="native",
        content_format="native",
        archive=ArchivedTranscript(sha256="a" * 64, size=1),
    )
    access = InstallationTranscriptAccess(db_pool, source)
    await access.require_read(capture)
    with pytest.raises(PermissionError):
        await InstallationTranscriptAccess(db_pool, "other").require_read(capture)
    try:
        await access.revoke(capture.archive)
        await access.revoke(capture.archive)
        restarted = InstallationTranscriptAccess(db_pool, source)
        for run_id in ("first", "shared-run"):
            with pytest.raises(PermissionError, match="revoked"):
                await restarted.require_read(
                    capture.model_copy(
                        update={"run": RunIdentity(source_instance_id=source, execution_id=run_id)}
                    )
                )
        await restarted.require_read(
            capture.model_copy(update={"archive": ArchivedTranscript(sha256="b" * 64, size=1)})
        )
        other = capture.model_copy(
            update={"run": RunIdentity(source_instance_id="other", execution_id="first")}
        )
        await InstallationTranscriptAccess(db_pool, "other").require_read(other)
    finally:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM session_transcript_revocations WHERE source_instance_id=$1", source
            )


async def test_local_revision_read_uses_real_archive_and_current_revocation(
    db_pool: asyncpg.Pool, inventory: PostgresSessionInventory, tmp_path: Path
) -> None:
    from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
    from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
    from syn_adapters.session_inventory.transcript_access import InstallationTranscriptAccess
    from syn_domain.contexts.agent_sessions import (
        CataloguedCapture,
        QualifiedSessionIdentity,
        ReadLocalTranscriptHandler,
    )

    source = str(uuid4())
    run = RunIdentity(source_instance_id=source, execution_id="run")
    identity = QualifiedSessionIdentity(
        kind="transcript", source_instance_id=source, harness="codex", local_id="native/雪"
    )
    archive = LocalSessionTranscriptArchive(tmp_path)
    catalog = PostgresCaptureCatalog(db_pool)
    access = InstallationTranscriptAccess(db_pool, source)
    body = b"first\r\n\x00\xff"
    first = await archive.put(body)
    second = await archive.put(b"resumed")
    try:
        for capture_id, reference in (("first", first), ("second", second)):
            await catalog.record(
                CataloguedCapture(
                    run=run,
                    producer_id="producer",
                    capture_id=capture_id,
                    harness="codex",
                    native_id=identity.local_id,
                    content_format="native",
                    archive=reference,
                )
            )
        reader = ReadLocalTranscriptHandler(catalog, archive, access)
        historical = await reader.handle(run, identity, first.sha256)
        assert historical.status == "present"
        assert historical.body == body
        assert (await reader.handle(run, identity, second.sha256)).body == b"resumed"
        await access.revoke(first)
        with pytest.raises(PermissionError, match="revoked"):
            await reader.handle(run, identity, first.sha256)
        assert (await reader.handle(run, identity, second.sha256)).body == b"resumed"
        (tmp_path / second.sha256).unlink()
        missing = await reader.handle(run, identity, second.sha256)
        assert missing.status == "missing"
        assert missing.body is None
    finally:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM session_transcript_revocations WHERE source_instance_id=$1", source
            )
            await conn.execute(
                "DELETE FROM session_capture_catalog WHERE source_instance_id=$1", source
            )


async def _stage_as_older_build(
    store: PostgresSessionInventory, db_pool: asyncpg.Pool, item: InventorySnapshot
) -> None:
    """Stage exactly what a build before namespace counts wrote: no `namespaces` key."""
    await ready(store, item)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_inventory_snapshots SET metadata = metadata #- '{counts,namespaces}'
            WHERE source_instance_id=$1 AND execution_id=$2 AND snapshot_id=$3""",
            item.run.source_instance_id,
            item.run.execution_id,
            item.snapshot_id,
        )
        raw = await conn.fetchval(
            "SELECT metadata->'counts' ? 'namespaces' FROM session_inventory_snapshots "
            "WHERE source_instance_id=$1 AND snapshot_id=$2",
            item.run.source_instance_id,
            item.snapshot_id,
        )
    assert raw is False  # The hazard is really the old shape, not a null field.


async def test_revision_staged_by_older_build_resumes_and_publishes_after_upgrade(
    inventory: PostgresSessionInventory,
    db_pool: asyncpg.Pool,
    run: RunIdentity,
) -> None:
    current = snapshot(run)
    legacy = current.without_derived_counts()
    await _stage_as_older_build(inventory, db_pool, legacy)
    await db_pool.expire_connections()
    upgraded = PostgresSessionInventory(db_pool)
    # The resumed job re-stages with the new metadata shape: an upgrade, not a conflict.
    await ready(upgraded, current)
    await upgraded.publish(run, current.snapshot_id, None)
    await upgraded.publish(run, current.snapshot_id, None)  # lost-response retry
    head = await upgraded.head(run)
    assert head == current
    assert head is not None and head.without_derived_counts() == legacy.without_derived_counts()
    page = await upgraded.page(run, current.snapshot_id, "node")
    assert page.items == nodes(run, 3)


async def test_revision_staged_by_older_build_publishes_without_restaging(
    inventory: PostgresSessionInventory,
    db_pool: asyncpg.Pool,
    run: RunIdentity,
) -> None:
    current = snapshot(run)
    legacy = current.without_derived_counts()
    await _stage_as_older_build(inventory, db_pool, legacy)
    upgraded = PostgresSessionInventory(db_pool)
    await upgraded.publish(run, legacy.snapshot_id, None)
    head = await upgraded.head(run)
    # Counts are completed deterministically from the stored node items.
    assert head == current


async def test_newer_metadata_survives_an_older_build_retry_and_real_changes_conflict(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
) -> None:
    current = snapshot(run)
    await ready(inventory, current)
    # An older build (no namespace counts) retrying the same revision is compatible.
    await inventory.stage(current.without_derived_counts())
    with pytest.raises(InventoryPublicationConflict, match="disagree with nodes"):
        await inventory.stage(
            current.model_copy(
                update={
                    "counts": current.counts.model_copy(
                        update={"namespaces": (InventoryNamespaceCount(kind="platform", count=3),)}
                    )
                }
            )
        )
    with pytest.raises(InventoryPublicationConflict, match="metadata"):
        await inventory.stage(current.without_derived_counts().model_copy(update={"revision": "x"}))
    await inventory.publish(run, current.snapshot_id, None)
    assert await inventory.head(run) == current


def _wrong_split(item: InventorySnapshot) -> InventorySnapshot:
    """Same node total as the stored nodes, different per-namespace split."""
    total = item.counts.node
    namespaces = (
        InventoryNamespaceCount(kind="platform", count=1),
        InventoryNamespaceCount(kind="transcript", harness="third-harness", count=total - 1),
    )
    return item.model_copy(
        update={"counts": item.counts.model_copy(update={"namespaces": namespaces})}
    )


@pytest.mark.parametrize("wrong_first", [True, False])
async def test_wrong_namespace_split_is_rejected_in_either_retry_order(
    inventory: PostgresSessionInventory,
    db_pool: asyncpg.Pool,
    run: RunIdentity,
    wrong_first: bool,
) -> None:
    current = snapshot(run)
    await _stage_as_older_build(inventory, db_pool, current.without_derived_counts())
    wrong = _wrong_split(current)
    if wrong_first:
        with pytest.raises(InventoryPublicationConflict, match="disagree with nodes"):
            await inventory.stage(wrong)
        await inventory.stage(current)
    else:
        await inventory.stage(current)
        with pytest.raises(InventoryPublicationConflict, match="disagree with nodes"):
            await inventory.stage(wrong)
    await inventory.publish(run, current.snapshot_id, None)
    assert await inventory.head(run) == current


async def test_publication_derives_counts_even_when_a_retry_could_not_be_checked(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
) -> None:
    current = snapshot(run)
    # Legacy staging before any node is stored: a wrong-split retry cannot be
    # checked yet, and must not become the published truth.
    await inventory.stage(current.without_derived_counts())
    await inventory.stage(_wrong_split(current))
    await inventory.append(run, current.snapshot_id, "node", 0, nodes(run, 3))
    await inventory.publish(run, current.snapshot_id, None)
    assert await inventory.head(run) == current


async def test_declared_counts_that_disagree_with_stored_nodes_never_publish(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
) -> None:
    wrong = _wrong_split(snapshot(run))
    await inventory.stage(wrong)
    await inventory.append(run, wrong.snapshot_id, "node", 0, nodes(run, 3))
    with pytest.raises(InventoryPublicationConflict, match="disagree with nodes"):
        await inventory.publish(run, wrong.snapshot_id, None)
    assert await inventory.head(run) is None
