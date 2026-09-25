"""Rows 10/11 (#1398): owner deletion, quotas and anti-resurrection on real storage.

Real PostgreSQL and a real content-addressed archive. A tombstone must withhold
bytes from the moment it is recorded, apply to every run sharing the object,
survive replay/retry/re-upload, propagate to the replica exactly once and keep
the session discoverable.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.body_availability import PostgresBodyAvailability
from syn_adapters.session_inventory.body_retention import LocalBodyRetention
from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
from syn_adapters.session_inventory.capture_delivery_jobs import (
    CaptureDeliveryLeaseLost,
    PostgresCaptureDeliveryJobs,
)
from syn_adapters.session_inventory.deletion_fence import DeletionFence
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.native_evidence import AgenticNativeSessionEvidence
from syn_adapters.session_inventory.transcript_access import InstallationTranscriptAccess
from syn_adapters.session_inventory.transcript_deletions import PostgresTranscriptDeletions
from syn_domain.contexts.agent_sessions import (
    BodyAvailability,
    CaptureLocalTranscriptHandler,
    CaptureReceipt,
    CataloguedCapture,
    EvidenceReference,
    InventoryCounts,
    InventoryCoverage,
    InventoryFilter,
    InventoryNodeRef,
    InventoryQueryPage,
    InventorySnapshot,
    LocalTranscriptCapture,
    QualifiedSessionIdentity,
    ReadLocalTranscriptHandler,
    RunIdentity,
    TranscriptDeletedError,
)

if TYPE_CHECKING:
    from pathlib import Path

    import asyncpg

pytestmark = pytest.mark.integration

CONTENT_HASH = "sha256:" + "c" * 64


def _envelope(native: str, raw: str = "exact\r\n") -> bytes:
    return json.dumps(
        {
            "scs_version": "1.0",
            "origin": {"host": "test", "environment": "local"},
            "agent": "codex",
            "source_format": "codex-rollout-jsonl",
            "session_id": native,
            "started_at": "2026-09-22T00:00:00Z",
            "last_activity_at": "2026-09-22T00:00:01Z",
            "raw": raw,
        }
    ).encode()


async def _record(
    pool: asyncpg.Pool,
    archive: LocalSessionTranscriptArchive,
    source: str,
    execution: str,
    body: bytes,
    *,
    capture_id: str,
    content_format: str = "native",
    native: str = "native",
) -> CataloguedCapture:
    capture = CataloguedCapture.model_validate(
        {
            "run": {"source_instance_id": source, "execution_id": execution},
            "producer_id": "test",
            "capture_id": capture_id,
            "harness": "codex",
            "native_id": native,
            "content_format": content_format,
            "archive": (await archive.put(body)).model_dump(),
        }
    )
    await PostgresCaptureCatalog(pool).record(capture)
    return capture


def _deletions(
    pool: asyncpg.Pool,
    source: str,
    archive: LocalSessionTranscriptArchive,
    destination: str | None,
) -> PostgresTranscriptDeletions:
    return PostgresTranscriptDeletions(
        pool, source, destination, archive=archive, fence=DeletionFence(pool, source)
    )


def _identity(capture: CataloguedCapture) -> QualifiedSessionIdentity:
    assert capture.native_id is not None
    return QualifiedSessionIdentity(
        kind="transcript",
        source_instance_id=capture.run.source_instance_id,
        harness=capture.harness,
        local_id=capture.native_id,
    )


def _page(run: RunIdentity, *receipts: CaptureReceipt) -> InventoryQueryPage:
    from uuid import uuid4 as _uuid

    return InventoryQueryPage(
        snapshot=InventorySnapshot(
            snapshot_id=_uuid(),
            run=run,
            revision="r",
            resolver_version="test/1",
            evidence_watermark=1,
            coverage=InventoryCoverage.model_validate({"state": "unknown"}),
            counts=InventoryCounts(node=0, membership=0, edge=0, capture=len(receipts), gap=0),
        ),
        kind="capture",
        filters=InventoryFilter(),
        items=receipts,
        item_keys=(),
        has_more=False,
    )


def _receipt(run: RunIdentity, *, local: str | None, remote: str | None) -> CaptureReceipt:
    return CaptureReceipt(
        node=InventoryNodeRef(
            kind="transcript",
            source_instance_id=run.source_instance_id,
            harness="codex",
            local_id="native",
        ),
        availability=BodyAvailability.PRESENT,
        receipt_sequence=0,
        evidence=EvidenceReference(
            evidence_id="e",
            producer_id="p",
            source_revision="r",
            locator="l",
            extractor_version="1",
        ),
        destination="local" if local is not None else "remote",
        transcript_revision=local if local is not None else remote,
        archived_byte_hash=local,
    )


async def test_owner_deletion_is_whole_object_idempotent_and_cannot_be_resurrected(
    db_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    evidence = PostgresSessionEvidence(db_pool)
    await evidence.ensure_ready()
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path / "archive")
    await archive.ensure_ready()
    body = _envelope("native")
    # The same bytes belong to two runs: one object, two memberships.
    first = await _record(
        db_pool, archive, source, "run-a", body, capture_id="a", content_format="envelope"
    )
    shared = await _record(
        db_pool, archive, source, "run-b", body, capture_id="b", content_format="envelope"
    )
    assert first.archive == shared.archive
    jobs = PostgresCaptureDeliveryJobs(db_pool, source, "replica")
    await jobs.discover()
    in_flight = await jobs.claim()
    assert in_flight is not None
    # This delivery reached the exporter's enqueue step: its content hash is durable.
    await jobs.record_content_hash(in_flight, CONTENT_HASH)
    access = InstallationTranscriptAccess(db_pool, source)
    reader = ReadLocalTranscriptHandler(PostgresCaptureCatalog(db_pool), archive, access)
    deletions = _deletions(db_pool, source, archive, "replica")

    state, created = await deletions.request(first, "deletion")
    assert created and state.reason == "deletion" and state.local_status == "pending"
    assert state.replication == "propagate"
    assert [r.status for r in state.replicas] == ["pending"]
    assert state.source_content_hash == CONTENT_HASH
    again, created_again = await deletions.request(shared, "retraction")
    assert not created_again
    assert again.reason == "deletion" and again.requested_at == state.requested_at

    # Withheld immediately for every sharing run: the archive marker denies
    # reads and puts although erasure has not run yet.
    assert (tmp_path / "archive" / first.archive.sha256).read_bytes() == body
    assert await archive.get(first.archive) is None
    for capture in (first, shared):
        assert await access.tombstone(capture) == "deleted"
        read = await reader.handle(capture.run, _identity(capture), capture.archive.sha256)
        assert read.status == "deleted" and read.body is None
    # A delivery leased before the request cannot complete; no new claim appears.
    with pytest.raises(CaptureDeliveryLeaseLost):
        await jobs.finish(in_flight, queued=True)
    assert await jobs.claim() is None

    # No automatic retention configured: owner deletions still run, and need no
    # local bytes or exporter because the content hash was recorded at enqueue.
    retention = LocalBodyRetention(db_pool, archive, source)
    assert await retention.drain() == 1
    assert not (tmp_path / "archive" / first.archive.sha256).exists()
    erased = await deletions.state(first)
    assert erased is not None and erased.local_status == "deleted"
    assert erased.deleted_at is not None and erased.source_content_hash == CONTENT_HASH

    # Resurrection attempts: re-upload, replayed capture, retry, new destination.
    with pytest.raises(TranscriptDeletedError):
        await archive.put(body)
    capture_handler = CaptureLocalTranscriptHandler(
        archive, evidence, AgenticNativeSessionEvidence(), catalog=PostgresCaptureCatalog(db_pool)
    )
    with pytest.raises(TranscriptDeletedError):
        await capture_handler.handle(
            LocalTranscriptCapture(
                run=first.run,
                capture_id="replayed",
                harness="codex",
                receipt_sequence=9,
                content=body,
                content_format="envelope",
            )
        )
    restarted = LocalSessionTranscriptArchive(tmp_path / "archive")
    assert await restarted.get(first.archive) is None
    fresh = PostgresCaptureDeliveryJobs(db_pool, source, "new-replica")
    await fresh.discover()
    assert await fresh.claim() is None
    assert not await LocalBodyRetention(db_pool, archive, source).step()

    # Discoverability: catalog rows and the exact revision lookup remain.
    catalog = PostgresCaptureCatalog(db_pool)
    assert await catalog.get(first.run, "test", "a") == first
    assert await catalog.get_revision(shared.run, _identity(shared), shared.archive.sha256)
    overrides = await PostgresBodyAvailability(db_pool).overrides(
        _page(
            first.run,
            _receipt(first.run, local=first.archive.sha256, remote=None),
            _receipt(first.run, local=None, remote=CONTENT_HASH),
        )
    )
    assert [(o.archive_sha256, o.source_content_hash, o.status) for o in overrides] == [
        (first.archive.sha256, CONTENT_HASH, "deleted")
    ]


async def test_revocation_withholds_shared_object_and_deletion_takes_precedence(
    db_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    first = await _record(db_pool, archive, source, "run-a", b"shared", capture_id="a")
    shared = await _record(db_pool, archive, source, "run-b", b"shared", capture_id="b")
    access = InstallationTranscriptAccess(db_pool, source)
    reader = ReadLocalTranscriptHandler(PostgresCaptureCatalog(db_pool), archive, access)
    assert await access.revoke(first.archive)
    assert not await access.revoke(first.archive)
    with pytest.raises(PermissionError):
        await reader.handle(shared.run, _identity(shared), shared.archive.sha256)
    assert await archive.get(shared.archive) == b"shared"  # revocation retains bytes
    page = _page(shared.run, _receipt(shared.run, local=shared.archive.sha256, remote=None))
    availability = PostgresBodyAvailability(db_pool)
    assert [o.status for o in await availability.overrides(page)] == ["withheld"]
    await _deletions(db_pool, source, archive, None).request(first, "retraction")
    assert [o.status for o in await availability.overrides(page)] == ["deleted"]
    # Another installation's policy never touches this object.
    other = InstallationTranscriptAccess(db_pool, str(uuid4()))
    with pytest.raises(PermissionError):
        await other.tombstone(first)


async def test_retention_expiry_is_expired_not_deleted_and_quota_counts_objects_once(
    db_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    oldest = await _record(db_pool, archive, source, "run", b"o" * 40, capture_id="old")
    await _record(db_pool, archive, source, "other-run", b"o" * 40, capture_id="old-shared")
    middle = await _record(db_pool, archive, source, "run", b"m" * 40, capture_id="middle")
    newest = await _record(db_pool, archive, source, "run", b"n" * 40, capture_id="new")
    async with db_pool.acquire() as conn:
        for capture_id, age in (("old", 3), ("old-shared", 1), ("middle", 2), ("new", 0)):
            await conn.execute(
                """UPDATE session_capture_catalog
                SET created_at=now()-$3::double precision*interval '1 hour'
                WHERE source_instance_id=$1 AND capture_id=$2""",
                source,
                capture_id,
                age,
            )
    # 120 bytes of distinct objects; the shared object counts once, not twice.
    retention = LocalBodyRetention(db_pool, archive, source, max_bytes=80)
    assert await retention.drain() == 1
    assert await archive.get(oldest.archive) is None
    assert await archive.get(middle.archive) == b"m" * 40
    assert await archive.get(newest.archive) == b"n" * 40
    assert not await retention.step()  # within quota now
    access = InstallationTranscriptAccess(db_pool, source)
    assert await access.tombstone(oldest) == "expired"
    state = await _deletions(db_pool, source, archive, None).state(oldest)
    assert state is not None and state.reason == "retention_quota"
    assert state.replication == "disabled" and state.replicas == ()
    reader = ReadLocalTranscriptHandler(PostgresCaptureCatalog(db_pool), archive, access)
    read = await reader.handle(oldest.run, _identity(oldest), oldest.archive.sha256)
    assert read.status == "expired" and read.capture == oldest
    # An owner request for an already-expired body keeps the original reason.
    again, created = await _deletions(db_pool, source, archive, None).request(oldest, "deletion")
    assert not created and again.reason == "retention_quota"
    with pytest.raises(ValueError):
        LocalBodyRetention(db_pool, archive, source, max_bytes=0)
