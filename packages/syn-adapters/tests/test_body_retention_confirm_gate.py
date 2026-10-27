"""Automatic expiry behind a confirmed remote copy, on a real database (#2107 S5).

A gated expiry deletes bytes only when the archive confirms every uploaded
revision the body backs. Any other answer keeps the bytes, withdraws the
automatic tombstone and holds the body. Owner deletions are never gated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.body_retention import LocalBodyRetention
from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
from syn_adapters.session_inventory.capture_deletion_worker import CaptureDeletionWorker
from syn_adapters.session_inventory.capture_delivery_jobs import PostgresCaptureDeliveryJobs
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.expiry_gate import ConfirmedExpiryGate, ExpiryHold
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_domain.contexts.agent_sessions import CataloguedCapture, RunIdentity
from syn_domain.contexts.agent_sessions.ports.SessionArchiveSinkPort import (
    ArchiveUnavailable,
    RevisionAbsent,
    RevisionConfirmation,
    RevisionConfirmed,
    UploadedRevision,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_DEST = "replica"
_HASH = "sha256:" + "c" * 64
_CONFIRMED = RevisionConfirmed(stored_content_hash="sha256:" + "d" * 64, body_verified=True)


class _Sink:
    def __init__(self, answer: RevisionConfirmation) -> None:
        self.answer = answer
        self.asked: list[UploadedRevision] = []

    async def confirm(self, revision: UploadedRevision) -> RevisionConfirmation:
        self.asked.append(revision)
        return self.answer


async def _aged_envelope(pool, archive, source: str, name: str, *, upload: bool):
    await PostgresSessionEvidence(pool).ensure_ready()
    ref = await archive.put(name.encode())
    capture = CataloguedCapture(
        run=RunIdentity(source_instance_id=source, execution_id="gate-run"),
        producer_id="test",
        capture_id=name,
        harness="claude",
        native_id=name,
        content_format="envelope",
        archive=ref,
    )
    await PostgresCaptureCatalog(pool).record(capture)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_capture_catalog SET created_at=now()-interval '2 days' "
            "WHERE source_instance_id=$1",
            source,
        )
    if upload:
        # The real delivery path: hash persisted before enqueue, then a receipt.
        jobs = PostgresCaptureDeliveryJobs(pool, source, _DEST)
        await jobs.discover()
        lease = await jobs.claim()
        assert lease is not None
        await jobs.record_content_hash(lease, _HASH)
        await jobs.finish(lease, queued=True)
        receipt = await jobs.claim_receipt()
        assert receipt is not None
        await jobs.finish_receipt(receipt, recorded=True)
    return capture


def _retention(pool, archive, source: str, sink: _Sink, *, attested: bool = True):
    gate = ConfirmedExpiryGate(sink, offsite_backup_attested=attested)
    worker = LocalBodyRetention(
        pool, archive, source, age_seconds=86400, gate=gate, destination_id=_DEST
    )
    return worker, gate


async def _deletions(pool, source: str) -> list[tuple[str, bool]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT reason,(deleted_at IS NOT NULL)::text AS done FROM session_body_deletions "
            "WHERE source_instance_id=$1",
            source,
        )
    return [(row["reason"], row["done"] == "true") for row in rows]


async def _hold(pool, source: str) -> str | None:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT hold FROM session_body_retention_holds WHERE source_instance_id=$1", source
        )


async def test_confirmed_revision_lets_expiry_delete_and_asks_for_what_was_uploaded(
    db_pool, tmp_path: Path
) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_envelope(db_pool, archive, source, "confirmed", upload=True)
    sink = _Sink(_CONFIRMED)
    worker, gate = _retention(db_pool, archive, source, sink)
    assert await worker.step()
    assert await archive.get(capture.archive) is None
    assert sink.asked == [
        UploadedRevision(
            source_instance_id=source,
            harness="claude",
            native_session_id="confirmed",
            content_hash=_HASH,
        )
    ]
    assert gate.permitted == 1
    assert await _deletions(db_pool, source) == [("retention_age", True)]


@pytest.mark.parametrize(
    ("answer", "hold"),
    [(RevisionAbsent(), ExpiryHold.ABSENT), (ArchiveUnavailable(), ExpiryHold.UNAVAILABLE)],
)
async def test_unconfirmed_revision_keeps_the_bytes_and_holds_the_body(
    db_pool, tmp_path: Path, answer: RevisionConfirmation, hold: ExpiryHold
) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_envelope(db_pool, archive, source, "held", upload=True)
    sink = _Sink(answer)
    worker, gate = _retention(db_pool, archive, source, sink)
    assert await worker.step()
    assert await archive.get(capture.archive) == b"held"
    # The automatic tombstone is withdrawn, so reads and delivery are not blocked.
    assert await _deletions(db_pool, source) == []
    assert await _hold(db_pool, source) == hold.value
    assert gate.holds[hold] == 1
    # Held: not rediscovered, not asked again, bytes still there.
    assert not await worker.step()
    assert len(sink.asked) == 1
    assert await archive.get(capture.archive) == b"held"


async def test_without_backup_attestation_nothing_expires_and_the_archive_is_not_asked(
    db_pool, tmp_path: Path
) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_envelope(db_pool, archive, source, "unattested", upload=True)
    sink = _Sink(_CONFIRMED)
    worker, _ = _retention(db_pool, archive, source, sink, attested=False)
    assert await worker.step()
    assert await archive.get(capture.archive) == b"unattested"
    assert sink.asked == []
    assert await _hold(db_pool, source) == ExpiryHold.NO_BACKUP_ATTESTATION.value


async def test_body_never_uploaded_is_not_tombstoned_under_the_gate(
    db_pool, tmp_path: Path
) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_envelope(db_pool, archive, source, "local-only", upload=False)
    sink = _Sink(_CONFIRMED)
    worker, _ = _retention(db_pool, archive, source, sink)
    assert not await worker.step()
    assert await _deletions(db_pool, source) == []
    assert await archive.get(capture.archive) == b"local-only"
    # Flag off is today's behaviour: the same body expires ungated.
    assert await LocalBodyRetention(db_pool, archive, source, age_seconds=86400).step()
    assert await archive.get(capture.archive) is None


async def test_pending_automatic_tombstone_from_before_the_gate_is_still_gated(
    db_pool, tmp_path: Path
) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_envelope(db_pool, archive, source, "legacy", upload=False)
    await LocalBodyRetention(db_pool, archive, source, age_seconds=86400).discover()
    worker, _ = _retention(db_pool, archive, source, _Sink(_CONFIRMED))
    assert await worker.step()
    assert await archive.get(capture.archive) == b"legacy"
    assert await _hold(db_pool, source) == ExpiryHold.NOT_UPLOADED.value


async def test_owner_deletion_is_never_gated(db_pool, tmp_path: Path) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_envelope(db_pool, archive, source, "owner", upload=True)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive,reason) "
            "VALUES($1,$2,$3::jsonb,'deletion')",
            source,
            capture.archive.sha256,
            capture.archive.model_dump_json(),
        )
    sink = _Sink(RevisionAbsent())
    worker, _ = _retention(db_pool, archive, source, sink)
    assert await worker.step()
    assert await archive.get(capture.archive) is None
    assert sink.asked == []


@pytest.mark.parametrize(("propagate", "sent"), [(True, True), (False, False)])
async def test_gated_expiry_is_not_propagated_to_the_archive(
    db_pool, tmp_path: Path, propagate: bool, sent: bool
) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    await _aged_envelope(db_pool, archive, source, "kept-remote", upload=True)
    worker, _ = _retention(db_pool, archive, source, _Sink(_CONFIRMED))
    assert await worker.step()
    transport = AsyncMock()
    deletions = CaptureDeletionWorker(db_pool, transport, source, _DEST, propagate_expiry=propagate)
    assert await deletions.step() is sent
    assert transport.delete.await_count == int(sent)
