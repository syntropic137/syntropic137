"""Review pass 1 (#1398): after a deletion request no path delivers or derives facts.

Real PostgreSQL, real archive, real fence. The exporter and replica are recording
doubles that keep bytes, so assertions are about what the replica actually
received. The exporter double is deliberately pessimistic: a strict FIFO outbox
where a queued delete does NOT supersede an earlier queued upload. The replica
models the behaviour the real SeshMagic integration test verifies: once it holds
a deletion tombstone it rejects (410) a delayed upload of that content.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from apss_session_capture.inventory import QualifiedTranscript

from syn_adapters.session_inventory.body_retention import LocalBodyRetention
from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
from syn_adapters.session_inventory.capture_deletion_worker import CaptureDeletionWorker
from syn_adapters.session_inventory.capture_delivery_jobs import PostgresCaptureDeliveryJobs
from syn_adapters.session_inventory.capture_delivery_worker import CaptureDeliveryWorker
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

    from syn_domain.contexts.agent_sessions import NativeTranscriptFacts

pytestmark = pytest.mark.integration

DESTINATION = "replica"


def _hash(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(b"apss-content:" + body).hexdigest()


@dataclass
class Replica:
    online: bool = True
    bodies: dict[tuple[str, str], bytes] = field(default_factory=dict)
    tombstones: set[tuple[str, str]] = field(default_factory=set)
    received: list[bytes] = field(default_factory=list)
    """Every body the replica ever accepted, even if later deleted."""

    def serve(self, identity: QualifiedTranscript) -> list[bytes]:
        key = identity.storage_key()
        return [body for (k, _), body in self.bodies.items() if k == key]


@dataclass
class Exporter:
    """Strict FIFO outbox; nothing is superseded, so ordering alone must be safe."""

    replica: Replica
    outbox: list[tuple[str, QualifiedTranscript, str, bytes]] = field(default_factory=list)

    async def content_hash(self, envelope: bytes) -> str:
        return _hash(envelope)

    async def enqueue(self, identity: QualifiedTranscript, envelope: bytes) -> EnqueueReceipt:
        self.outbox.append(("upload", identity, _hash(envelope), envelope))
        return EnqueueReceipt(schema_version=1, inserted=True)

    async def delete(self, identity: QualifiedTranscript, content_hash: str) -> EnqueueReceipt:
        self.outbox.append(("delete", identity, content_hash, b""))
        return EnqueueReceipt(schema_version=1, inserted=True)

    async def drain(self, limit: int = 1) -> CaptureDrain:
        if not self.outbox:
            return CaptureDrain(acknowledged=0, failed=0, remaining=0)
        if not self.replica.online:
            return CaptureDrain(acknowledged=0, failed=1, remaining=len(self.outbox))
        acknowledged = 0
        for _ in range(min(limit, len(self.outbox))):
            op, identity, content_hash, body = self.outbox.pop(0)
            key = (identity.storage_key(), content_hash)
            if op == "delete":
                self.replica.tombstones.add(key)
                self.replica.bodies.pop(key, None)
                acknowledged += 1
            elif key not in self.replica.tombstones:
                self.replica.bodies[key] = body
                self.replica.received.append(body)
                acknowledged += 1
            # else: 410 for a delayed upload; cancelled without acknowledgement.
        return CaptureDrain(acknowledged=acknowledged, failed=0, remaining=len(self.outbox))


@dataclass
class Stack:
    pool: asyncpg.Pool
    source: str
    archive: LocalSessionTranscriptArchive
    replica: Replica
    uploads: Exporter
    deletes: Exporter
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


@pytest.fixture
async def stack(db_pool: asyncpg.Pool, tmp_path: Path) -> Stack:
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    archive = LocalSessionTranscriptArchive(tmp_path / "archive")
    await archive.ensure_ready()
    replica = Replica()
    uploads, deletes = Exporter(replica), Exporter(replica)
    fence = DeletionFence(db_pool, source)
    worker = CaptureDeliveryWorker(
        PostgresCaptureDeliveryJobs(db_pool, source, DESTINATION),
        archive,
        uploads,  # type: ignore[arg-type]  # recording double of the exporter seam
        deletions=CaptureDeletionWorker(db_pool, deletes, source, DESTINATION),
        fence=fence,
        retry_seconds=0,
    )
    deletions = PostgresTranscriptDeletions(
        db_pool, source, DESTINATION, archive=archive, fence=fence
    )
    return Stack(db_pool, source, archive, replica, uploads, deletes, worker, deletions, tmp_path)


async def test_enqueued_then_deleted_body_never_reaches_the_replica(stack: Stack) -> None:
    body = b'{"agent":"codex","session_id":"native","raw":"private"}'
    capture = await stack.capture(body)
    assert await stack.worker.enqueue_step()  # upload now sits in the exporter outbox
    assert [op for op, *_ in stack.uploads.outbox] == ["upload"]
    stack.replica.online = False
    await stack.deletions.request(capture, "deletion")
    # Fenced: the upload outbox is not drained while the deletion is unacknowledged.
    assert await stack.worker.drain_step() is None
    await stack.worker.enqueue_step()  # queues the delete in its own outbox
    assert await stack.replica_status(capture) == "queued"
    for _ in range(3):  # replica down: retries never report propagation
        await stack.worker.enqueue_step()
        assert await stack.worker.drain_step() is None
    assert await stack.replica_status(capture) == "queued"
    stack.replica.online = True
    await stack.worker.enqueue_step()  # delete acknowledged by the replica
    assert await stack.replica_status(capture) == "propagated"
    drained = await stack.worker.drain_step()
    assert drained is not None and drained.acknowledged == 0  # 410: delayed upload dropped
    assert stack.replica.received == []
    assert (
        stack.replica.serve(
            QualifiedTranscript(
                source_instance_id=stack.source, harness="codex", native_session_id="native"
            )
        )
        == []
    )


async def test_deleted_before_enqueue_is_never_enqueued_or_sent(stack: Stack) -> None:
    capture = await stack.capture(b'{"raw":"never"}')
    await stack.deletions.request(capture, "retraction")
    assert not await stack.worker.enqueue_step()
    assert stack.uploads.outbox == [] and stack.deletes.outbox == []
    drained = await stack.worker.drain_step()
    assert drained is not None and drained.remaining == 0
    state = await stack.deletions.state(capture)
    assert state is not None and state.replication == "not_applicable"
    assert stack.replica.received == []


async def test_request_waits_for_an_in_flight_drain(stack: Stack) -> None:
    capture = await stack.capture(b'{"raw":"racing"}')
    assert await stack.worker.enqueue_step()
    started, release = asyncio.Event(), asyncio.Event()
    inner = stack.uploads.drain

    async def slow_drain(limit: int = 1) -> CaptureDrain:
        started.set()
        await release.wait()
        return await inner(limit)

    stack.uploads.drain = slow_drain  # type: ignore[method-assign]
    drain = asyncio.create_task(stack.worker.drain_step())
    await started.wait()
    request = asyncio.create_task(stack.deletions.request(capture, "deletion"))
    await asyncio.sleep(0.2)
    # The tombstone cannot take effect while a send it would forbid is in flight.
    assert not request.done()
    assert await stack.archive.get(capture.archive) is not None
    release.set()
    await drain
    await request
    # The upload finished before the request took effect; deletion then follows.
    assert stack.replica.received == [b'{"raw":"racing"}']
    await stack.worker.enqueue_step()
    await stack.worker.enqueue_step()
    assert await stack.replica_status(capture) == "propagated"
    assert stack.replica.bodies == {}


async def test_replica_deletion_progresses_after_local_bytes_are_gone(stack: Stack) -> None:
    body = b'{"raw":"erased first"}'
    capture = await stack.capture(body)
    assert await stack.worker.enqueue_step()
    assert (await stack.worker.drain_step()) is not None
    assert stack.replica.received == [body]
    (stack.root / "archive" / capture.archive.sha256).unlink()  # local body lost
    await stack.deletions.request(capture, "deletion")
    # No exporter configured and no bytes: the enqueue-time hash is enough.
    assert await LocalBodyRetention(stack.pool, stack.archive, stack.source).drain() == 1
    await stack.worker.enqueue_step()
    await stack.worker.enqueue_step()
    assert await stack.replica_status(capture) == "propagated"
    assert stack.replica.bodies == {}
    assert stack.deletes.outbox == []


async def test_empty_outbox_without_acknowledgement_is_requeued_not_propagated(
    stack: Stack,
) -> None:
    capture = await stack.capture(b'{"raw":"dropped"}')
    assert await stack.worker.enqueue_step()
    await stack.deletions.request(capture, "deletion")
    await stack.worker.enqueue_step()
    stack.deletes.outbox.clear()  # exporter lost the delete without acknowledging it
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
