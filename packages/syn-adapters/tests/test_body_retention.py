"""Real database expiry, bounded work and deletion acknowledgement recovery."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.body_retention import LocalBodyRetention
from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_domain.contexts.agent_sessions import (
    CataloguedCapture,
    RunIdentity,
    TranscriptDeletedError,
)

pytestmark = pytest.mark.integration


async def _capture(pool, archive, source, identity):
    ref = await archive.put(identity.encode())
    capture = CataloguedCapture(
        run=RunIdentity(source_instance_id=source, execution_id="retention-run"),
        producer_id="test",
        capture_id=identity,
        harness="claude",
        native_id=identity,
        content_format="native",
        archive=ref,
    )
    await PostgresCaptureCatalog(pool).record(capture)
    return capture


async def test_expiry_is_bounded_and_preserves_catalog(db_pool, tmp_path):
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source, other = str(uuid4()), str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    first = await _capture(db_pool, archive, source, "first")
    second = await _capture(db_pool, archive, source, "second")
    foreign = await _capture(db_pool, archive, other, "foreign")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_capture_catalog SET created_at=now()-interval '2 days' WHERE source_instance_id=ANY($1)",
            [source, other],
        )
    fresh = await _capture(db_pool, archive, source, "fresh")
    worker = LocalBodyRetention(db_pool, archive, source, age_seconds=86400)
    await worker.discover(limit=1)
    async with db_pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM session_body_deletions WHERE source_instance_id=$1", source
            )
            == 1
        )
    assert await worker.step()
    remaining = [await archive.get(c.archive) for c in (first, second)]
    assert sum(body is None for body in remaining) == 1
    assert await worker.step()
    assert not await worker.step()
    for capture in (first, second):
        assert await archive.get(capture.archive) is None
        assert (
            await PostgresCaptureCatalog(db_pool).get(capture.run, "test", capture.capture_id)
            == capture
        )
        with pytest.raises(TranscriptDeletedError):
            await archive.put(capture.capture_id.encode())
    assert await archive.get(fresh.archive) == b"fresh"
    assert await archive.get(foreign.archive) == b"foreign"


async def test_crash_after_unlink_retries_durable_request(db_pool, tmp_path):
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _capture(db_pool, archive, source, "crash")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_capture_catalog SET created_at=now()-interval '2 days' WHERE source_instance_id=$1",
            source,
        )
    failing_archive = AsyncMock(wraps=archive)

    async def crash(ref):
        await archive.delete(ref)
        raise OSError("interrupted before SQL acknowledgement")

    failing_archive.delete.side_effect = crash
    worker = LocalBodyRetention(db_pool, failing_archive, source, age_seconds=86400)
    with pytest.raises(OSError, match="interrupted"):
        await worker.step()
    assert await archive.get(capture.archive) is None
    async with db_pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM session_body_deletions WHERE source_instance_id=$1 AND deleted_at IS NULL",
                source,
            )
            == 1
        )
    restarted = LocalBodyRetention(
        db_pool, LocalSessionTranscriptArchive(tmp_path), source, age_seconds=86400
    )
    assert await restarted.step()
    assert not await restarted.step()


@pytest.mark.parametrize("already_queued", [False, True])
async def test_expiry_cancels_delivery_and_fences_claimed_worker(
    db_pool, tmp_path, already_queued, monkeypatch
):
    from syn_adapters.session_inventory.capture_delivery_jobs import (
        CaptureDeliveryLeaseLost,
        PostgresCaptureDeliveryJobs,
    )

    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _capture(db_pool, archive, source, "delivery")
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_capture_catalog SET payload=jsonb_set(payload,'{content_format}','\"envelope\"'::jsonb),created_at=now()-interval '2 days' WHERE source_instance_id=$1",
            source,
        )
    jobs = PostgresCaptureDeliveryJobs(db_pool, source, "replica")
    await jobs.discover()
    lease = await jobs.claim()
    assert lease is not None
    receipt_lease = None
    if already_queued:
        await jobs.finish(lease, queued=True)
        receipt_lease = await jobs.claim_receipt()
        assert receipt_lease is not None
    from pathlib import Path

    monkeypatch.setattr(
        "syn_adapters.session_inventory.body_retention.original_envelope_hash",
        AsyncMock(return_value="sha256:" + "a" * 64),
    )
    retention = LocalBodyRetention(
        db_pool, archive, source, age_seconds=86400, exporter_binary=Path("/fixture/exporter")
    )
    # One step: a legacy queued delivery (no enqueue-time hash) derives its
    # replica deletion key from the still-present bytes before erasure.
    assert await retention.step()
    async with db_pool.acquire() as conn:
        recorded = await conn.fetchval(
            "SELECT content_hash FROM session_body_deletions WHERE source_instance_id=$1",
            source,
        )
    assert recorded == ("sha256:" + "a" * 64 if already_queued else None)
    with pytest.raises(CaptureDeliveryLeaseLost):
        await jobs.renew(lease)
    with pytest.raises(CaptureDeliveryLeaseLost):
        await jobs.finish(lease, queued=True)
    if receipt_lease is not None:
        with pytest.raises(CaptureDeliveryLeaseLost):
            await jobs.finish_receipt(receipt_lease, recorded=True)
    assert await jobs.claim() is None
    assert await jobs.claim_receipt() is None
    fresh_destination = PostgresCaptureDeliveryJobs(db_pool, source, "new-replica")
    await fresh_destination.discover()
    assert await fresh_destination.claim() is None
    assert await archive.get(capture.archive) is None


async def test_real_exporter_retains_deletion_key_before_body_removal(db_pool, tmp_path):
    import json
    import os
    from pathlib import Path

    from pydantic import SecretStr

    from syn_adapters.session_inventory.capture_deletion_worker import CaptureDeletionWorker
    from syn_adapters.session_inventory.exporter_transport import (
        ExporterCaptureTransport,
        ExporterConfig,
    )

    binary = os.environ.get("SYN_TEST_EXPORTER_BINARY")
    if not binary:
        pytest.skip("requires current standard exporter binary")
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    body = json.dumps(
        {
            "scs_version": "1.0",
            "origin": {"host": "test", "environment": "local"},
            "agent": "codex",
            "source_format": "codex-rollout-jsonl",
            "session_id": "native",
            "started_at": "2026-09-22T00:00:00Z",
            "last_activity_at": "2026-09-22T00:00:01Z",
            "raw": "exact\r\n",
        }
    ).encode()
    ref = await archive.put(body)
    capture = CataloguedCapture(
        run=RunIdentity(source_instance_id=source, execution_id="run"),
        producer_id="test",
        capture_id="envelope",
        harness="codex",
        native_id="native",
        content_format="envelope",
        archive=ref,
    )
    await PostgresCaptureCatalog(db_pool).record(capture)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_capture_catalog SET created_at=now()-interval '2 days' WHERE source_instance_id=$1",
            source,
        )
    retention = LocalBodyRetention(
        db_pool, archive, source, age_seconds=86400, exporter_binary=Path(binary)
    )
    assert await retention.step()
    assert await archive.get(ref) is None
    transport = ExporterCaptureTransport(
        ExporterConfig(
            binary=Path(binary),
            outbox_dir=tmp_path / "queue",
            store_url="http://127.0.0.1:1",
            token=SecretStr("test-only"),
        )
    )
    failed = AsyncMock()
    failed.delete.side_effect = OSError("interrupted")
    with pytest.raises(OSError):
        await CaptureDeletionWorker(db_pool, failed, source, "replica").step()
    assert await CaptureDeletionWorker(db_pool, transport, source, "replica").step()
    assert not await CaptureDeletionWorker(db_pool, transport, source, "replica").step()
    pending = await transport.drain()
    assert pending.failed == 1 and pending.remaining == 1
    assert await CaptureDeletionWorker(db_pool, transport, source, "new-replica").step()
