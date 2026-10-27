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
    # Every delete ever handed over; a discard cannot erase this record.
    delete_calls: list[str] = field(default_factory=list)
    # A failed removal: raise and leave every queued item in place.
    discard_error: OSError | None = None

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
        self.delete_calls.append(content_hash)
        self.items.append(("delete", content_hash, b""))
        return EnqueueReceipt(schema_version=1, inserted=True)

    async def discard(self) -> None:
        if self.discard_error is not None:
            raise self.discard_error
        self.items.clear()

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


async def _deletion_checkpoints(stack: Stack) -> int:
    async with stack.pool.acquire() as conn:
        return int(
            await conn.fetchval(
                """SELECT count(*) FROM session_capture_deletion_checkpoints
                WHERE source_instance_id=$1""",
                stack.source,
            )
        )


async def _delivered(stack: Stack, body: bytes) -> CataloguedCapture:
    capture = await stack.capture(body)
    assert await stack.worker.enqueue_step()
    assert (await stack.worker.drain_step()) is not None
    assert stack.wire.sent == [body]
    return capture


@pytest.mark.parametrize("expiry", ["retention_age", "retention_quota", "default"])
async def test_automatic_expiry_never_deletes_the_replica_copy(stack: Stack, expiry: str) -> None:
    """#2107: the replica is what made local expiry safe; it must survive it.

    ``default`` is a tombstone written before reasons were recorded. Asserted
    after one deletion-worker step and on a cumulative record of every delete
    handed to the exporter, so no later cancellation could mask an enqueue.
    """
    body = b'{"raw":"expires locally, kept remotely"}'
    capture = await _delivered(stack, body)
    if expiry == "retention_age":
        retention = await _expire_by_age(stack, erase=True)
    elif expiry == "retention_quota":
        retention = LocalBodyRetention(stack.pool, stack.archive, stack.source, max_bytes=1)
        assert await retention.drain() == 1
    else:
        async with stack.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive)
                VALUES($1,$2,$3::jsonb)""",
                stack.source,
                capture.archive.sha256,
                capture.archive.model_dump_json(),
            )
        retention = LocalBodyRetention(stack.pool, stack.archive, stack.source)
        assert await retention.drain() == 1
    assert await stack.archive.get(capture.archive) is None  # local bytes gone
    worker = CaptureDeletionWorker(stack.pool, stack.deletes, stack.source, DESTINATION)
    assert not await worker.step()  # nothing to queue
    assert stack.deletes.delete_calls == []
    assert await _deletion_checkpoints(stack) == 0
    await stack.churn()
    assert stack.deletes.delete_calls == [] and stack.wire.deleted == []
    assert await _deletion_checkpoints(stack) == 0
    state = await stack.deletions.state(capture)
    assert state is not None and state.reason == (
        "retention_age" if expiry == "default" else expiry
    )
    assert state.local_status == "deleted"
    assert state.replication == "not_applicable" and state.replicas == ()


@pytest.mark.parametrize("reason", ["deletion", "retraction"])
async def test_owner_deletion_and_retraction_still_delete_the_replica_copy(
    stack: Stack, reason: str
) -> None:
    body = b'{"raw":"owner withdraws it"}'
    capture = await _delivered(stack, body)
    await stack.deletions.request(capture, reason)  # type: ignore[arg-type]  # parametrized literal
    assert await LocalBodyRetention(stack.pool, stack.archive, stack.source).drain() == 1
    await stack.churn()
    assert stack.wire.deleted == [_hash(body)]
    assert await stack.replica_status(capture) == "propagated"


async def test_owner_deletion_propagates_while_automatic_expiry_beside_it_does_not(
    stack: Stack,
) -> None:
    # Delivered one at a time: only the newest revision per transcript queues.
    owned = await stack.capture(b'{"raw":"owner"}', "owned")
    await stack.churn()
    expired = await stack.capture(b'{"raw":"expired"}', "expired")
    await stack.churn()
    assert stack.wire.sent == [b'{"raw":"owner"}', b'{"raw":"expired"}']
    async with stack.pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_capture_catalog SET created_at=now()-interval '2 days'
            WHERE source_instance_id=$1 AND capture_id='expired'""",
            stack.source,
        )
    retention = LocalBodyRetention(stack.pool, stack.archive, stack.source, age_seconds=86400)
    assert await retention.drain() == 1
    await stack.deletions.request(owned, "deletion")
    assert await retention.drain() == 1
    await stack.churn()
    assert stack.wire.deleted == [_hash(b'{"raw":"owner"}')]
    assert await stack.replica_status(owned) == "propagated"
    state = await stack.deletions.state(expired)
    assert state is not None and state.replication == "not_applicable"


async def _expire_by_age(stack: Stack, *, erase: bool) -> LocalBodyRetention:
    async with stack.pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_capture_catalog SET created_at=now()-interval '2 days'
            WHERE source_instance_id=$1""",
            stack.source,
        )
    retention = LocalBodyRetention(stack.pool, stack.archive, stack.source, age_seconds=86400)
    if erase:
        assert await retention.drain() == 1
    else:
        await retention.discover()
    return retention


@pytest.mark.parametrize("reason", ["deletion", "retraction"])
@pytest.mark.parametrize("expiry", ["pending", "completed"])
async def test_owner_request_promotes_an_automatic_tombstone_and_propagates(
    stack: Stack, reason: str, expiry: str
) -> None:
    """Owner intent arriving during or after automatic expiry is never swallowed."""
    body = b'{"raw":"owner after expiry"}'
    capture = await _delivered(stack, body)
    retention = await _expire_by_age(stack, erase=expiry == "completed")
    before = await stack.deletions.state(capture)
    assert before is not None and before.reason == "retention_age"
    await stack.churn()
    assert stack.wire.deleted == []
    state, created = await stack.deletions.request(capture, reason)  # type: ignore[arg-type]  # parametrized literal
    assert created and state.reason == reason
    assert state.requested_at == before.requested_at  # same tombstone, promoted
    await retention.drain()
    await stack.churn()
    assert stack.wire.deleted == [_hash(body)]
    assert await stack.replica_status(capture) == "propagated"
    # Owner intent is never downgraded by later automatic expiry passes.
    await retention.drain()
    after = await stack.deletions.state(capture)
    assert after is not None and after.reason == reason


async def test_repeated_owner_request_keeps_the_original_owner_reason(stack: Stack) -> None:
    capture = await _delivered(stack, b'{"raw":"owner twice"}')
    await stack.deletions.request(capture, "retraction")
    state, created = await stack.deletions.request(capture, "deletion")
    assert not created and state.reason == "retraction"


async def _older_build_left(stack: Stack, *, checkpointed: CataloguedCapture | None) -> None:
    """The deployment as an older build left it: no purge recorded yet."""
    async with stack.pool.acquire() as conn:
        await conn.execute(
            """DELETE FROM session_capture_deletion_outbox_purges
            WHERE source_instance_id=$1""",
            stack.source,
        )
        if checkpointed is not None:
            await conn.execute(
                """INSERT INTO session_capture_deletion_checkpoints
                (source_instance_id,destination_id,producer_id,capture_id,content_hash)
                VALUES($1,$2,$3,$4,'x')""",
                stack.source,
                DESTINATION,
                checkpointed.producer_id,
                checkpointed.capture_id,
            )


async def _purge_recorded(stack: Stack) -> bool:
    async with stack.pool.acquire() as conn:
        return (
            await conn.fetchval(
                """SELECT count(*)::text FROM session_capture_deletion_outbox_purges
                WHERE source_instance_id=$1 AND destination_id=$2""",
                stack.source,
                DESTINATION,
            )
            == "1"
        )


async def test_checkpointed_automatic_delete_from_an_older_build_is_purged_unsent(
    stack: Stack,
) -> None:
    body = b'{"raw":"queued by an older build"}'
    capture = await _delivered(stack, body)
    await _expire_by_age(stack, erase=True)
    stack.deletes.items.append(("delete", _hash(body), b""))
    await _older_build_left(stack, checkpointed=capture)
    restarted = CaptureDeletionWorker(stack.pool, stack.deletes, stack.source, DESTINATION)
    assert await restarted.step()  # purge, before any drain
    assert not await restarted.step()  # nothing left, nothing requeued
    await stack.churn()
    assert stack.wire.deleted == [] and stack.deletes.items == []
    assert await _deletion_checkpoints(stack) == 0 and await _purge_recorded(stack)


async def _owned_and_expired(stack: Stack) -> tuple[CataloguedCapture, CataloguedCapture]:
    """Both delivered (owner first: only the newest revision per transcript queues),
    then only ``expired`` aged out and erased locally."""
    owned = await stack.capture(OWNED_BODY, "owned")
    await stack.churn()
    expired = await stack.capture(EXPIRED_BODY, "expired")
    await stack.churn()
    assert stack.wire.sent == [OWNED_BODY, EXPIRED_BODY]
    async with stack.pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_capture_catalog SET created_at=now()-interval '2 days'
            WHERE source_instance_id=$1 AND capture_id='expired'""",
            stack.source,
        )
    retention = LocalBodyRetention(stack.pool, stack.archive, stack.source, age_seconds=86400)
    assert await retention.drain() == 1
    return owned, expired


OWNED_BODY, EXPIRED_BODY = b'{"raw":"owner"}', b'{"raw":"expired"}'


async def test_crash_between_exporter_enqueue_and_checkpoint_commit_is_purged(
    stack: Stack,
) -> None:
    """Orphaned automatic delete, no checkpoint: an owner delete must not drain it."""
    owned, expired = await _owned_and_expired(stack)
    # The older build enqueued the automatic delete, then died before its
    # checkpoint committed.
    stack.deletes.items.append(("delete", _hash(EXPIRED_BODY), b""))
    await _older_build_left(stack, checkpointed=None)
    await stack.deletions.request(owned, "deletion")
    await stack.churn(4)
    assert stack.wire.deleted == [_hash(OWNED_BODY)]
    assert await stack.replica_status(owned) == "propagated"
    state = await stack.deletions.state(expired)
    assert state is not None and state.replication == "not_applicable"


async def test_failed_outbox_removal_records_no_purge_and_drains_nothing(
    stack: Stack,
) -> None:
    owned, expired = await _owned_and_expired(stack)
    stack.deletes.items.append(("delete", _hash(EXPIRED_BODY), b""))
    await _older_build_left(stack, checkpointed=expired)
    stack.deletes.discard_error = PermissionError("outbox entry not removable")
    restarted = CaptureDeletionWorker(stack.pool, stack.deletes, stack.source, DESTINATION)
    for _ in range(3):
        with pytest.raises(PermissionError):
            await restarted.step()
    await stack.deletions.request(owned, "deletion")
    await stack.churn(4)  # failures are logged and retried, never drained past
    assert stack.wire.deleted == []
    assert stack.deletes.items == [("delete", _hash(EXPIRED_BODY), b"")]
    assert await _deletion_checkpoints(stack) == 1  # the older build's, kept
    assert not await _purge_recorded(stack)
    stack.deletes.discard_error = None  # removal works again
    await stack.churn(4)
    assert stack.wire.deleted == [_hash(OWNED_BODY)]
    assert await _purge_recorded(stack)


async def test_owner_delete_in_flight_from_an_older_build_is_regenerated(stack: Stack) -> None:
    body = b'{"raw":"owner in flight"}'
    capture = await _delivered(stack, body)
    await stack.deletions.request(capture, "deletion")
    stack.wire.online = False
    await stack.churn(2)
    assert await stack.replica_status(capture) == "queued"
    stack.wire.online = True
    await _older_build_left(stack, checkpointed=None)
    restarted = CaptureDeletionWorker(stack.pool, stack.deletes, stack.source, DESTINATION)
    for _ in range(4):
        await restarted.step()
    assert stack.wire.deleted == [_hash(body)]
    assert await stack.replica_status(capture) == "propagated"
