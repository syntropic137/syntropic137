"""Automatic expiry behind a confirmed remote copy, on a real database (#2107 S5).

A gated expiry deletes bytes only when the archive confirms the newest uploaded
revision the body backs. Any other answer keeps the bytes, withdraws the
automatic tombstone and holds the body. Older revisions never expire. Owner
deletions are never gated, and owner intent is never withdrawn.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.body_retention import LocalBodyRetention
from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
from syn_adapters.session_inventory.deletion_fence import DeletionFence
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.expiry_gate import ConfirmedExpiryGate, ExpiryHold
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.transcript_deletions import PostgresTranscriptDeletions
from syn_domain.contexts.agent_sessions import CataloguedCapture, RunIdentity
from syn_domain.contexts.agent_sessions.ports.SessionArchiveSinkPort import (
    ArchiveUnavailable,
    RevisionAbsent,
    RevisionConfirmation,
    RevisionConfirmed,
    UploadedRevision,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

pytestmark = pytest.mark.integration

_DEST = "replica"
_CONFIRMED = RevisionConfirmed(stored_content_hash="sha256:" + "d" * 64, body_verified=True)


def _hash(name: str) -> str:
    return "sha256:" + hashlib.sha256(name.encode()).hexdigest()


class _Sink:
    def __init__(
        self,
        answer: RevisionConfirmation,
        before: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.answer, self.before = answer, before
        self.asked: list[UploadedRevision] = []

    async def confirm(self, revision: UploadedRevision) -> RevisionConfirmation:
        self.asked.append(revision)
        if self.before is not None:
            await self.before()
        return self.answer


async def _capture(pool, archive, source: str, name: str, body: bytes, *, native: str):
    await PostgresSessionEvidence(pool).ensure_ready()
    ref = await archive.put(body)
    capture = CataloguedCapture(
        run=RunIdentity(source_instance_id=source, execution_id="gate-run"),
        producer_id="test",
        capture_id=name,
        harness="claude",
        native_id=native,
        content_format="envelope",
        archive=ref,
    )
    await PostgresCaptureCatalog(pool).record(capture)
    return capture


async def _age(pool, source: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE session_capture_catalog SET created_at=now()-interval '2 days' "
            "WHERE source_instance_id=$1",
            source,
        )


async def _upload(pool, source: str, capture: CataloguedCapture) -> None:
    """A delivered revision: hash persisted before enqueue, then a receipt.

    Jobs are inserted directly for the exact capture, as deliveries queued
    before #2110 did for older revisions too.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO session_capture_delivery_jobs
            (destination_id,source_instance_id,producer_id,capture_id,queued,
             content_hash,receipt_recorded,outbox_drained)
            VALUES($1,$2,$3,$4,TRUE,$5,TRUE,TRUE)""",
            _DEST,
            source,
            capture.producer_id,
            capture.capture_id,
            _hash(capture.capture_id),
        )


async def _aged_uploaded(pool, archive, source: str, name: str):
    capture = await _capture(pool, archive, source, name, name.encode(), native=name)
    await _age(pool, source)
    await _upload(pool, source, capture)
    return capture


def _retention(pool, archive, source: str, sink: _Sink, *, attested: bool = True, **kw):
    gate = ConfirmedExpiryGate(sink, offsite_backup_attested=attested)
    worker = LocalBodyRetention(
        pool, archive, source, age_seconds=86400, gate=gate, destination_id=_DEST, **kw
    )
    return worker, gate


async def _deletions(pool, source: str) -> list[tuple[str, bool]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT reason,(deleted_at IS NOT NULL)::text AS done FROM session_body_deletions "
            "WHERE source_instance_id=$1 ORDER BY reason",
            source,
        )
    return [(row["reason"], row["done"] == "true") for row in rows]


async def _hold(pool, source: str) -> str | None:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT hold FROM session_body_retention_holds WHERE source_instance_id=$1", source
        )


async def test_confirmed_newest_revision_expires_and_the_archive_is_asked_for_it(
    db_pool, tmp_path: Path
) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_uploaded(db_pool, archive, source, "confirmed")
    sink = _Sink(_CONFIRMED)
    worker, gate = _retention(db_pool, archive, source, sink)
    assert await worker.step()
    assert await archive.get(capture.archive) is None
    assert sink.asked == [
        UploadedRevision(
            source_instance_id=source,
            harness="claude",
            native_session_id="confirmed",
            content_hash=_hash("confirmed"),
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
    capture = await _aged_uploaded(db_pool, archive, source, "held")
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
    capture = await _aged_uploaded(db_pool, archive, source, "unattested")
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
    capture = await _capture(db_pool, archive, source, "local", b"local", native="local")
    await _age(db_pool, source)
    worker, _ = _retention(db_pool, archive, source, _Sink(_CONFIRMED))
    assert not await worker.step()
    assert await _deletions(db_pool, source) == []
    assert await archive.get(capture.archive) == b"local"
    # Flag off is today's behaviour: the same body expires ungated.
    assert await LocalBodyRetention(db_pool, archive, source, age_seconds=86400).step()
    assert await archive.get(capture.archive) is None


async def test_an_older_revision_never_expires_even_when_it_was_uploaded(
    db_pool, tmp_path: Path
) -> None:
    """R1: only the newest full revision is eligible. A pre-#2110 delivery
    uploaded older revisions too; they still never expire under the gate."""
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    older = await _capture(db_pool, archive, source, "older", b"prefix", native="t")
    newest = await _capture(db_pool, archive, source, "newest", b"prefix+more", native="t")
    await _age(db_pool, source)
    for capture in (older, newest):
        await _upload(db_pool, source, capture)
    sink = _Sink(_CONFIRMED)
    worker, _ = _retention(db_pool, archive, source, sink)
    assert await worker.step()
    assert not await worker.step()
    assert await archive.get(older.archive) == b"prefix"
    assert await archive.get(newest.archive) is None
    assert [r.native_session_id for r in sink.asked] == ["t"]
    assert [r.content_hash for r in sink.asked] == [_hash("newest")]
    # An automatic tombstone recorded before the gate is withdrawn, not executed.
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive,reason) "
            "VALUES($1,$2,$3::jsonb,'retention_age')",
            source,
            older.archive.sha256,
            older.archive.model_dump_json(),
        )
    assert await worker.step()
    assert await archive.get(older.archive) == b"prefix"
    assert await _hold(db_pool, source) == ExpiryHold.OLDER_REVISION.value


async def test_a_splice_base_is_held_so_its_references_are_not_inflated(
    db_pool, tmp_path: Path
) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_uploaded(db_pool, archive, source, "base")
    archive.is_splice_base = AsyncMock(return_value=True)  # type: ignore[method-assign]
    sink = _Sink(_CONFIRMED)
    worker, _ = _retention(db_pool, archive, source, sink)
    assert await worker.step()
    assert await archive.get(capture.archive) == b"base"
    assert sink.asked == []
    assert await _hold(db_pool, source) == ExpiryHold.SPLICE_BASE.value


async def test_owner_deletion_is_never_gated(db_pool, tmp_path: Path) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_uploaded(db_pool, archive, source, "owner")
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


async def test_owner_deletion_onto_a_pending_expiry_is_finished_not_withdrawn(
    db_pool, tmp_path: Path
) -> None:
    """Codex P1: the owner request finds the automatic row and promotes it to
    owner intent (#2128); its archive marker says so too. The refusing gate
    must not withdraw it."""
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_uploaded(db_pool, archive, source, "intent")
    await LocalBodyRetention(db_pool, archive, source, age_seconds=86400).discover()
    owner = PostgresTranscriptDeletions(
        db_pool, source, _DEST, archive=archive, fence=DeletionFence(db_pool, source)
    )
    await owner.request(capture, "deletion")
    sink = _Sink(RevisionAbsent())
    worker, _ = _retention(db_pool, archive, source, sink)
    assert await worker.step()
    assert await _deletions(db_pool, source) == [("deletion", True)]
    assert await _hold(db_pool, source) is None
    assert sink.asked == []


async def test_owner_deletion_during_the_confirmation_is_not_withdrawn(
    db_pool, tmp_path: Path
) -> None:
    """The owner acts while the archive is being asked, after the marker check."""
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_uploaded(db_pool, archive, source, "racing")
    owner = PostgresTranscriptDeletions(
        db_pool, source, _DEST, archive=archive, fence=DeletionFence(db_pool, source)
    )

    async def owner_deletes() -> None:
        await owner.request(capture, "deletion")

    worker, _ = _retention(db_pool, archive, source, _Sink(RevisionAbsent(), owner_deletes))
    assert await worker.step()
    assert await _hold(db_pool, source) is None
    assert await _deletions(db_pool, source) == [("deletion", True)]
    assert await archive.get(capture.archive) is None


async def test_crash_after_unlink_resumes_finalization_and_never_withdraws(
    db_pool, tmp_path: Path
) -> None:
    """Codex P2: bytes are gone but SQL never committed. The retry must not
    confirm again, withdraw the tombstone and record a hold."""
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    capture = await _aged_uploaded(db_pool, archive, source, "crashed")
    failing = AsyncMock(wraps=archive)

    async def crash(ref):
        await archive.delete(ref)
        raise OSError("interrupted before SQL acknowledgement")

    failing.delete.side_effect = crash
    worker, _ = _retention(db_pool, failing, source, _Sink(_CONFIRMED))
    with pytest.raises(OSError, match="interrupted"):
        await worker.step()
    assert await _deletions(db_pool, source) == [("retention_age", False)]
    sink = _Sink(ArchiveUnavailable())
    restarted, _ = _retention(db_pool, archive, source, sink)
    assert await restarted.step()
    assert await _deletions(db_pool, source) == [("retention_age", True)]
    assert await _hold(db_pool, source) is None
    assert sink.asked == []
    assert await archive.get(capture.archive) is None


async def test_one_drain_asks_the_archive_a_bounded_number_of_times(
    db_pool, tmp_path: Path
) -> None:
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    for n in range(6):
        await _aged_uploaded(db_pool, archive, source, f"bounded-{n}")
    sink = _Sink(ArchiveUnavailable())
    worker, _ = _retention(db_pool, archive, source, sink, max_confirms=4)
    assert await worker.drain() == 4
    assert len(sink.asked) == 4
    assert await worker.drain() == 2
    assert len(sink.asked) == 6


async def test_holds_report_bodies_and_bytes_by_reason(db_pool, tmp_path: Path) -> None:
    """What /health shows: every kept body once, under its latest reason."""
    from syn_adapters.session_inventory.expiry_holds import PostgresExpiryHolds

    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path)
    older = await _capture(db_pool, archive, source, "older", b"prefix", native="t")
    newest = await _capture(db_pool, archive, source, "newest", b"prefix+more", native="t")
    local = await _capture(db_pool, archive, source, "local", b"local-only", native="l")
    base = await _capture(db_pool, archive, source, "base", b"spliced-base", native="b")
    await _age(db_pool, source)
    for capture in (older, newest, base):
        await _upload(db_pool, source, capture)
    archive.is_splice_base = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda ref: ref.sha256 == base.archive.sha256
    )
    worker, _ = _retention(db_pool, archive, source, _Sink(RevisionAbsent()))
    await worker.drain()
    summary = await PostgresExpiryHolds(db_pool, source).summary()
    assert [(c.hold, c.bodies, c.bytes) for c in summary] == [
        (ExpiryHold.OLDER_REVISION, 1, len(b"prefix")),
        (ExpiryHold.NOT_UPLOADED, 1, len(b"local-only")),
        (ExpiryHold.SPLICE_BASE, 1, len(b"spliced-base")),
        (ExpiryHold.ABSENT, 1, len(b"prefix+more")),
    ]
    for capture in (older, newest, local, base):
        assert await archive.get(capture.archive) is not None
    # A held body the owner then deletes is no longer reported as held.
    owner = PostgresTranscriptDeletions(
        db_pool, source, _DEST, archive=archive, fence=DeletionFence(db_pool, source)
    )
    await owner.request(local, "deletion")
    assert await worker.step()
    assert ExpiryHold.NOT_UPLOADED not in [
        c.hold for c in await PostgresExpiryHolds(db_pool, source).summary()
    ]
