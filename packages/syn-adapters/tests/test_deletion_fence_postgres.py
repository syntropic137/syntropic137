"""Rows 10/11 (#1398): after a deletion request commits, withdrawn bytes never
leave this host again and are never served or used to derive facts.

Real PostgreSQL, real archive, real fence. The exporter is a recording double
of the per-capture outbox seam: every hand-off of bytes (``handed``) and every
send over the wire (``sent``) is logged, so assertions are about what the
exporter actually received and transmitted, not what a replica later rejected.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.body_retention import LocalBodyRetention
from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
from syn_adapters.session_inventory.capture_deletion_worker import CaptureDeletionWorker
from syn_adapters.session_inventory.capture_delivery_jobs import PostgresCaptureDeliveryJobs
from syn_adapters.session_inventory.capture_delivery_worker import CaptureDeliveryWorker
from syn_adapters.session_inventory.capture_outboxes import capture_outbox_key
from syn_adapters.session_inventory.deletion_fence import DeletionFence
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.exporter_transport import CaptureDrain, EnqueueReceipt
from syn_adapters.session_inventory.history_source import PostgresHistoricalEvidenceSource
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.native_evidence import AgenticNativeSessionEvidence
from syn_adapters.session_inventory.transcript_deletions import PostgresTranscriptDeletions
from syn_domain.contexts.agent_sessions import CataloguedCapture, RunIdentity

if TYPE_CHECKING:
    from pathlib import Path

    import asyncpg
    from apss_session_capture.inventory import QualifiedTranscript

    from syn_domain.contexts.agent_sessions import NativeTranscriptFacts

pytestmark = pytest.mark.integration

DESTINATION = "replica"


def _hash(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(b"apss-content:" + body).hexdigest()


@dataclass
class Wire:
    """Everything that left the exporter, and everything handed to it."""

    online: bool = True
    handed: list[bytes] = field(default_factory=list)
    sent: list[bytes] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


@dataclass
class Outbox:
    """Strict FIFO exporter outbox; it cannot cancel anything it holds."""

    wire: Wire
    items: list[tuple[str, str, bytes]] = field(default_factory=list)
    pause: asyncio.Event | None = None
    paused: asyncio.Event = field(default_factory=asyncio.Event)

    async def content_hash(self, envelope: bytes) -> str:
        return _hash(envelope)

    async def enqueue(self, identity: QualifiedTranscript, envelope: bytes) -> EnqueueReceipt:
        if self.pause is not None:
            self.paused.set()
            await self.pause.wait()
        self.wire.handed.append(envelope)
        self.items.append(("upload", _hash(envelope), envelope))
        return EnqueueReceipt(schema_version=1, inserted=True)

    async def delete(self, identity: QualifiedTranscript, content_hash: str) -> EnqueueReceipt:
        self.items.append(("delete", content_hash, b""))
        return EnqueueReceipt(schema_version=1, inserted=True)

    async def receipt(self, identity: QualifiedTranscript, envelope: bytes) -> None:
        self.wire.handed.append(envelope)

    async def drain(self, limit: int = 1) -> CaptureDrain:
        if self.pause is not None:
            self.paused.set()
            await self.pause.wait()
        if not self.items:
            return CaptureDrain(acknowledged=0, failed=0, remaining=0)
        if not self.wire.online:
            return CaptureDrain(acknowledged=0, failed=1, remaining=len(self.items))
        acknowledged = 0
        for _ in range(min(limit, len(self.items))):
            op, content_hash, body = self.items.pop(0)
            if op == "delete":
                self.wire.deleted.append(content_hash)
            else:
                self.wire.sent.append(body)
            acknowledged += 1
        return CaptureDrain(acknowledged=acknowledged, failed=0, remaining=len(self.items))


@dataclass
class Outboxes:
    wire: Wire
    boxes: dict[str, Outbox] = field(default_factory=dict)
    legacy: Outbox | None = None
    discarded: list[str] = field(default_factory=list)

    def for_capture(self, producer_id: str, capture_id: str) -> Outbox:
        key = capture_outbox_key(producer_id, capture_id)
        return self.boxes.setdefault(key, Outbox(self.wire))

    async def discard(self, producer_id: str, capture_id: str) -> None:
        key = capture_outbox_key(producer_id, capture_id)
        self.discarded.append(key)
        self.boxes.pop(key, None)

    async def retire_legacy(self) -> None:
        self.legacy = None


@dataclass
class Stack:
    pool: asyncpg.Pool
    source: str
    archive: LocalSessionTranscriptArchive
    wire: Wire
    outboxes: Outboxes
    deletes: Outbox
    worker: CaptureDeliveryWorker
    deletions: PostgresTranscriptDeletions
    root: Path

    async def capture(self, body: bytes, capture_id: str = "c") -> CataloguedCapture:
        capture = CataloguedCapture.model_validate(
            {
                "run": {"source_instance_id": self.source, "execution_id": "run"},
                "producer_id": "spool",
                "capture_id": capture_id,
                "harness": "codex",
                "native_id": "native",
                "content_format": "envelope",
                "archive": (await self.archive.put(body)).model_dump(),
            }
        )
        await PostgresCaptureCatalog(self.pool).record(capture)
        return capture

    async def replica_status(self, capture: CataloguedCapture) -> str:
        state = await self.deletions.state(capture)
        assert state is not None
        return state.replicas[0].status

    async def churn(self, rounds: int = 4) -> None:
        """Every delivery path, repeatedly: enqueue, receipts, drain, retries."""
        for _ in range(rounds):
            await self.worker.enqueue_step()
            await self.worker.receipt_step()
            await self.worker.drain_step()


@pytest.fixture
async def stack(db_pool: asyncpg.Pool, tmp_path: Path) -> Stack:
    evidence = PostgresSessionEvidence(db_pool)
    await evidence.ensure_ready()
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path / "archive")
    await archive.ensure_ready()
    wire = Wire()
    outboxes, deletes = Outboxes(wire), Outbox(wire)
    fence = DeletionFence(db_pool, source)
    worker = CaptureDeliveryWorker(
        PostgresCaptureDeliveryJobs(db_pool, source, DESTINATION),
        archive,
        outboxes,  # type: ignore[arg-type]  # recording double of the outbox seam
        deletions=CaptureDeletionWorker(db_pool, deletes, source, DESTINATION),
        journal=evidence,
        fence=fence,
        retry_seconds=0,
    )
    deletions = PostgresTranscriptDeletions(
        db_pool,
        source,
        DESTINATION,
        archive=archive,
        fence=fence,
        outboxes=outboxes,  # type: ignore[arg-type]
    )
    return Stack(db_pool, source, archive, wire, outboxes, deletes, worker, deletions, tmp_path)


async def test_enqueued_then_deleted_body_never_leaves_the_host(stack: Stack) -> None:
    body = b'{"agent":"codex","session_id":"native","raw":"private"}'
    capture = await stack.capture(body)
    stack.wire.online = False
    assert await stack.worker.enqueue_step()
    assert await stack.worker.drain_step() is not None  # remote down: still queued
    assert stack.wire.handed == [body] and stack.wire.sent == []
    await stack.deletions.request(capture, "deletion")
    handed = len(stack.wire.handed)
    # The queued upload is discarded with the request, not merely fenced.
    assert capture_outbox_key("spool", "c") not in stack.outboxes.boxes
    stack.wire.online = True
    await stack.churn()
    assert stack.wire.sent == [] and len(stack.wire.handed) == handed
    assert await stack.replica_status(capture) == "propagated"
    assert stack.wire.deleted == [_hash(body)]


async def test_failed_discard_at_request_is_still_never_sent(stack: Stack) -> None:
    """If discarding fails after the tombstone commits, the drain discards it."""
    body = b'{"raw":"discard failed"}'
    capture = await stack.capture(body)
    assert await stack.worker.enqueue_step()
    real = stack.outboxes.discard

    async def failing(producer_id: str, capture_id: str) -> None:
        raise OSError("disk busy")

    stack.outboxes.discard = failing  # type: ignore[method-assign]
    with pytest.raises(OSError):
        await stack.deletions.request(capture, "deletion")
    stack.outboxes.discard = real  # type: ignore[method-assign]
    assert capture_outbox_key("spool", "c") in stack.outboxes.boxes
    await stack.churn()
    assert stack.wire.sent == []
    assert capture_outbox_key("spool", "c") not in stack.outboxes.boxes


async def test_deleted_before_enqueue_is_never_handed_to_the_exporter(stack: Stack) -> None:
    capture = await stack.capture(b'{"raw":"never"}')
    await stack.deletions.request(capture, "retraction")
    await stack.churn()
    assert stack.wire.handed == [] and stack.wire.sent == []
    state = await stack.deletions.state(capture)
    assert state is not None and state.replication == "not_applicable"


@pytest.mark.parametrize("stage", ["enqueue", "drain"])
async def test_request_waits_for_an_in_flight_hand_off(stack: Stack, stage: str) -> None:
    body = b'{"raw":"racing"}'
    capture = await stack.capture(body)
    outbox = stack.outboxes.for_capture("spool", "c")
    if stage == "drain":
        assert await stack.worker.enqueue_step()
    release = asyncio.Event()
    outbox.pause = release
    step = asyncio.create_task(
        stack.worker.enqueue_step() if stage == "enqueue" else stack.worker.drain_step()
    )
    await outbox.paused.wait()
    request = asyncio.create_task(stack.deletions.request(capture, "deletion"))
    try:
        await asyncio.sleep(0.2)
        # The request cannot commit while bytes are mid-hand-off.
        assert not request.done()
    finally:
        release.set()
        await asyncio.wait_for(step, 10)
        await asyncio.wait_for(request, 10)
    outbox.pause = None
    sent_before = list(stack.wire.sent)
    handed_before = len(stack.wire.handed)
    # Whatever was in flight completed before the request; nothing follows it.
    assert capture_outbox_key("spool", "c") not in stack.outboxes.boxes
    await stack.churn()
    assert stack.wire.sent == sent_before
    assert len(stack.wire.handed) == handed_before
    assert stack.wire.sent == ([body] if stage == "drain" else [])


async def test_legacy_queued_upload_without_hash_or_bytes_is_never_sent(
    stack: Stack,
) -> None:
    """A pre-1398 shared outbox cannot be cancelled: it is never drained again."""
    withdrawn = b'{"raw":"legacy withdrawn"}'
    kept = b'{"raw":"legacy kept"}'
    gone = await stack.capture(withdrawn, "legacy-gone")
    alive = await stack.capture(kept, "legacy-kept")
    legacy = Outbox(stack.wire)
    legacy.items = [("upload", _hash(withdrawn), withdrawn), ("upload", _hash(kept), kept)]
    stack.outboxes.legacy = legacy
    async with stack.pool.acquire() as conn:
        # Queued by the old worker: no content hash was ever recorded.
        await conn.execute(
            """INSERT INTO session_capture_delivery_jobs
            (destination_id,source_instance_id,producer_id,capture_id,queued)
            VALUES ($1,$2,'spool','legacy-gone',TRUE),($1,$2,'spool','legacy-kept',TRUE)""",
            DESTINATION,
            stack.source,
        )
    (stack.root / "archive" / gone.archive.sha256).unlink()  # local bytes absent
    await stack.deletions.request(gone, "deletion")
    await stack.churn(6)
    assert stack.outboxes.legacy is None  # retired, never drained
    assert withdrawn not in stack.wire.sent and withdrawn not in stack.wire.handed
    # The non-withdrawn legacy capture is redelivered through its own outbox.
    assert stack.wire.sent == [kept]
    state = await stack.deletions.state(gone)
    assert state is not None and state.replicas[0].status == "unresolvable"
    assert alive.capture_id == "legacy-kept"


async def test_replica_deletion_progresses_after_local_bytes_are_gone(stack: Stack) -> None:
    body = b'{"raw":"erased first"}'
    capture = await stack.capture(body)
    assert await stack.worker.enqueue_step()
    assert (await stack.worker.drain_step()) is not None
    assert stack.wire.sent == [body]
    (stack.root / "archive" / capture.archive.sha256).unlink()  # local body lost
    await stack.deletions.request(capture, "deletion")
    # No exporter configured and no bytes: the enqueue-time hash is enough.
    assert await LocalBodyRetention(stack.pool, stack.archive, stack.source).drain() == 1
    await stack.churn(2)
    assert await stack.replica_status(capture) == "propagated"
    assert stack.wire.deleted == [_hash(body)]
    assert stack.wire.sent == [body]  # sent before the request only


async def test_unacknowledged_delete_is_queued_not_propagated_and_is_requeued(
    stack: Stack,
) -> None:
    capture = await stack.capture(b'{"raw":"dropped"}')
    assert await stack.worker.enqueue_step()
    await stack.deletions.request(capture, "deletion")
    stack.wire.online = False
    for _ in range(3):
        await stack.worker.enqueue_step()
        assert await stack.replica_status(capture) == "queued"
    stack.wire.online = True
    stack.deletes.items.clear()  # exporter lost the delete without acknowledging it
    await stack.worker.enqueue_step()
    assert await stack.replica_status(capture) == "pending"
    await stack.worker.enqueue_step()  # queued again
    await stack.worker.enqueue_step()  # acknowledged
    assert await stack.replica_status(capture) == "propagated"


@dataclass
class RecordingExtractor:
    seen: list[bytes] = field(default_factory=list)
    inner: AgenticNativeSessionEvidence = field(default_factory=AgenticNativeSessionEvidence)

    def extract(self, harness: str, body: bytes) -> NativeTranscriptFacts:
        self.seen.append(body)
        return self.inner.extract(harness, body)

    def extract_envelope(self, harness: str, body: bytes) -> NativeTranscriptFacts:
        self.seen.append(body)
        return self.inner.extract_envelope(harness, body)


class NoObservations:
    async def query_by_execution(self, *_: object, **__: object) -> list[object]:
        return []


@pytest.mark.parametrize("tombstone", ["request", "retention"])
async def test_backfill_derives_no_facts_from_a_withdrawn_body(
    stack: Stack, tombstone: str
) -> None:
    kept = json.dumps({"n": 1}).encode()
    withdrawn = json.dumps({"n": 2}).encode()
    stack_capture = await stack.capture(kept, "kept")
    removed = await stack.capture(withdrawn, "withdrawn")
    if tombstone == "request":
        await stack.deletions.request(removed, "deletion")
    else:
        # SQL-only retention tombstone: bytes and archive marker still present,
        # erasure held back; the SQL check alone must withhold them.
        async with stack.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive)
                VALUES($1,$2,$3::jsonb)""",
                stack.source,
                removed.archive.sha256,
                removed.archive.model_dump_json(),
            )
        assert await stack.archive.get(removed.archive) == withdrawn
    extractor = RecordingExtractor()
    source = PostgresHistoricalEvidenceSource(
        stack.pool,
        NoObservations(),
        stack.archive,
        extractor,
        max_observations=10,
        max_archives=10,
    )
    acquired = await source.acquire(
        RunIdentity(source_instance_id=stack.source, execution_id="run")
    )
    assert extractor.seen == [kept]
    facts = {item.capture_id: item.facts for item in acquired.archives}
    assert facts["withdrawn"] is None and facts["kept"] is not None
    assert stack_capture.capture_id == "kept"
