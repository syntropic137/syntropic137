"""Local-only reconstruction through real archive, journal, resolver and SQL."""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.postgres_inventory import PostgresSessionInventory
from syn_domain.contexts.agent_sessions import EvidenceBatch, InventoryNotFound, RunIdentity
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    CaptureEvidence,
    CoverageContract,
    InvocationContextEvidence,
    LineageEvidence,
    MembershipEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    BodyAvailability,
    CoverageState,
    EvidenceClass,
    EvidenceReference,
    InventoryGap,
    InventoryNodeRef,
)
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    RESOLVER_VERSION,
)
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.BuildInventorySnapshotHandler import (
    BuildInventorySnapshotHandler,
    EvidenceQuotaExceeded,
)

if TYPE_CHECKING:
    from pathlib import Path

    import asyncpg

pytestmark = pytest.mark.integration


def reference(identity: str) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=identity,
        producer_id="fake-adapter",
        source_revision="1",
        locator=identity,
        extractor_version="third-harness/1",
    )


async def test_local_only_depth_three_missing_body_and_late_capture(
    db_pool: asyncpg.Pool,
    tmp_path: Path,
) -> None:
    run = RunIdentity(source_instance_id=f"pipeline-{uuid4()}", execution_id="workflow-run")
    journal = PostgresSessionEvidence(db_pool)
    inventory = PostgresSessionInventory(db_pool)
    archive = LocalSessionTranscriptArchive(tmp_path)
    await journal.ensure_ready()
    await archive.ensure_ready()
    refs = tuple(
        InventoryNodeRef(
            kind="transcript",
            source_instance_id=run.source_instance_id,
            harness="third-harness",
            local_id=name,
        )
        for name in ("leader", "child", "grandchild")
    )
    source = SessionEvidence(
        run=run,
        edges=tuple(
            LineageEvidence(
                parent=parent,
                child=child,
                relation="spawn",
                confidence=EvidenceClass.CORROBORATED,
                evidence=reference(child.local_id),
            )
            for parent, child in pairwise(refs)
        ),
        coverage_contract=CoverageContract(
            contract_id="capture/1", expected_nodes=refs, sealed=True
        ),
    )
    await journal.append(
        EvidenceBatch(batch_id="relationships", producer_id="adapter", evidence=source)
    )
    captures: list[CaptureEvidence] = []
    for ref in refs[:2]:
        body = await archive.put(ref.local_id.encode())
        captures.append(
            CaptureEvidence(
                node=ref,
                availability=BodyAvailability.PRESENT,
                receipt_sequence=1,
                evidence=reference(f"body-{ref.local_id}"),
                archived_byte_hash=body.sha256,
            )
        )
    await journal.append(
        EvidenceBatch(
            batch_id="bodies",
            producer_id="capture",
            evidence=SessionEvidence(
                run=run,
                captures=tuple(captures),
            ),
        )
    )
    request = ReconciliationRequest(
        run=run,
        evidence_watermark=2,
        expected_head=None,
        snapshot_id=uuid4(),
        resolver_version=RESOLVER_VERSION,
    )
    handler = BuildInventorySnapshotHandler(
        journal, inventory, max_evidence_records=100, max_evidence_batches=100
    )
    first = await handler.handle(request)
    assert first.coverage.state is CoverageState.MISSING
    assert first.coverage.missing_keys == (refs[2].key,)
    assert await inventory.head(run) is None
    with pytest.raises(InventoryNotFound):
        await inventory.page(run, first.snapshot_id, "edge")
    await inventory.publish(run, first.snapshot_id, None)
    assert len((await inventory.page(run, first.snapshot_id, "edge")).items) == 2
    late_body = await archive.put(b"late grandchild bytes")
    await journal.append(
        EvidenceBatch(
            batch_id="late-body",
            producer_id="capture",
            evidence=SessionEvidence(
                run=run,
                captures=(
                    CaptureEvidence(
                        node=refs[2],
                        availability=BodyAvailability.PRESENT,
                        receipt_sequence=1,
                        evidence=reference("late-grandchild"),
                        archived_byte_hash=late_body.sha256,
                    ),
                ),
            ),
        )
    )
    # The original request is reproducible even with newer input now available.
    assert await handler.handle(request) == first
    second_request = request.model_copy(
        update={
            "evidence_watermark": 3,
            "snapshot_id": uuid4(),
            "expected_head": first.snapshot_id,
        }
    )
    second = await handler.handle(second_request)
    assert second.coverage.state is CoverageState.RECONCILED
    await inventory.publish(run, second.snapshot_id, first.snapshot_id)
    assert (
        await inventory.page(run, first.snapshot_id, "capture")
    ).snapshot.coverage.state is CoverageState.MISSING
    assert len((await inventory.page(run, second.snapshot_id, "capture")).items) == 3
    assert await LocalSessionTranscriptArchive(tmp_path).get(late_body) == b"late grandchild bytes"


async def test_quota_failure_keeps_committed_inventory_unchanged(db_pool: asyncpg.Pool) -> None:
    run = RunIdentity(source_instance_id=f"quota-{uuid4()}", execution_id="run")
    journal = PostgresSessionEvidence(db_pool)
    inventory = PostgresSessionInventory(db_pool)
    await journal.ensure_ready()
    await journal.append(
        EvidenceBatch(batch_id="first", producer_id="test", evidence=SessionEvidence(run=run))
    )
    request = ReconciliationRequest(
        run=run,
        evidence_watermark=1,
        expected_head=None,
        snapshot_id=uuid4(),
        resolver_version=RESOLVER_VERSION,
    )
    handler = BuildInventorySnapshotHandler(
        journal, inventory, max_evidence_records=1, max_evidence_batches=1
    )
    first = await handler.handle(request)
    await inventory.publish(run, first.snapshot_id, None)
    await journal.append(
        EvidenceBatch(batch_id="later", producer_id="test", evidence=SessionEvidence(run=run))
    )
    with pytest.raises(EvidenceQuotaExceeded):
        await handler.handle(
            request.model_copy(
                update={
                    "evidence_watermark": 2,
                    "snapshot_id": uuid4(),
                    "expected_head": first.snapshot_id,
                }
            )
        )
    assert await inventory.head(run) == first


async def test_native_bytes_to_central_graph_with_late_child_and_exact_archive(
    db_pool: asyncpg.Pool,
    tmp_path: Path,
) -> None:
    import json

    from syn_adapters.session_inventory.native_evidence import AgenticNativeSessionEvidence
    from syn_domain.contexts.agent_sessions import (
        CaptureLocalTranscriptHandler,
        LocalTranscriptCapture,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import LineageEdge

    run = RunIdentity(source_instance_id=f"native-{uuid4()}", execution_id="run")
    journal, inventory = PostgresSessionEvidence(db_pool), PostgresSessionInventory(db_pool)
    archive = LocalSessionTranscriptArchive(tmp_path)
    await journal.ensure_ready()
    await archive.ensure_ready()
    capture = CaptureLocalTranscriptHandler(archive, journal, AgenticNativeSessionEvidence())
    parent_bytes = (
        b'{"sessionId":"root", "message":{"content":[{"type":"tool_use",'
        b'"name":"Agent","id":"call"}]}}\r\n'
        b'{"sessionId":"root","message":{"content":[{"type":"tool_result",'
        b'"tool_use_id":"call"}]},"toolUseResult":{"agentId":"child"}}\r\n\n'
    )
    request = LocalTranscriptCapture(
        run=run,
        capture_id="parent-revision",
        harness="claude",
        receipt_sequence=1,
        content=parent_bytes,
    )
    saved = await capture.handle(request)
    assert await capture.handle(request) == saved
    assert await LocalSessionTranscriptArchive(tmp_path).get(saved.archive) == parent_bytes
    builder = BuildInventorySnapshotHandler(
        journal,
        inventory,
        max_evidence_records=100,
        max_evidence_batches=100,
    )
    first_request = ReconciliationRequest(
        run=run,
        evidence_watermark=saved.evidence_watermark,
        expected_head=None,
        snapshot_id=uuid4(),
        resolver_version=RESOLVER_VERSION,
    )
    first = await builder.handle(first_request)
    await inventory.publish(run, first.snapshot_id, None)
    first_edge = (await inventory.page(run, first.snapshot_id, "edge")).items[0]
    assert isinstance(first_edge, LineageEdge)
    assert first_edge.confidence == EvidenceClass.CANDIDATE
    assert first_edge.child.local_id == "agent-child"
    late = await capture.handle(
        LocalTranscriptCapture(
            run=run,
            capture_id="child-revision",
            harness="claude",
            receipt_sequence=1,
            content=json.dumps(
                {"sessionId": "root", "agentId": "child", "isSidechain": True}
            ).encode(),
        )
    )
    second = await builder.handle(
        first_request.model_copy(
            update={
                "snapshot_id": uuid4(),
                "evidence_watermark": late.evidence_watermark,
                "expected_head": first.snapshot_id,
            }
        )
    )
    await inventory.publish(run, second.snapshot_id, first.snapshot_id)
    second_edge = (await inventory.page(run, second.snapshot_id, "edge")).items[0]
    assert isinstance(second_edge, LineageEdge)
    assert second_edge.confidence == EvidenceClass.CORROBORATED
    assert second_edge.parent.local_id == "root"
    assert len(second_edge.evidence) == 3
    assert second.coverage.state == CoverageState.UNKNOWN
    assert (await inventory.page(run, first.snapshot_id, "edge")).items[0] == first_edge


class _InterruptCaptureEvidence(PostgresSessionEvidence):
    """Real durable journal with one injected process-interruption boundary."""

    interrupted = False
    calls = 0

    async def append(self, batch: EvidenceBatch) -> int:
        self.calls += 1
        if self.calls == 3 and not self.interrupted:
            self.interrupted = True
            raise ConnectionError("capture worker interrupted between durable pages")
        return await super().append(batch)


async def test_large_native_inventory_capture_retries_without_duplicates_or_truncation(
    db_pool: asyncpg.Pool,
    tmp_path: Path,
) -> None:
    import json

    from syn_adapters.session_inventory.native_evidence import AgenticNativeSessionEvidence
    from syn_domain.contexts.agent_sessions import (
        CaptureLocalTranscriptHandler,
        LocalTranscriptCapture,
    )

    run = RunIdentity(source_instance_id=f"large-native-{uuid4()}", execution_id="run")
    journal = _InterruptCaptureEvidence(db_pool)
    inventory = PostgresSessionInventory(db_pool)
    archive = LocalSessionTranscriptArchive(tmp_path)
    await journal.ensure_ready()
    await archive.ensure_ready()
    records: list[str] = []
    for index in range(1103):
        records.extend(
            (
                json.dumps(
                    {
                        "sessionId": "root",
                        "message": {
                            "content": [
                                {"type": "tool_use", "name": "Agent", "id": f"call-{index}"},
                            ]
                        },
                    }
                ),
                json.dumps(
                    {
                        "sessionId": "root",
                        "message": {
                            "content": [
                                {"type": "tool_result", "tool_use_id": f"call-{index}"},
                            ]
                        },
                        "toolUseResult": {"agentId": f"child-{index}"},
                    }
                ),
            )
        )
    request = LocalTranscriptCapture(
        run=run,
        capture_id="large-revision",
        harness="claude",
        receipt_sequence=1,
        content="\n".join(records).encode(),
    )
    capture = CaptureLocalTranscriptHandler(archive, journal, AgenticNativeSessionEvidence())
    with pytest.raises(ConnectionError):
        await capture.handle(request)
    # Discard the entire capture worker, reconnect its durable journal, and retry.
    restarted = CaptureLocalTranscriptHandler(
        LocalSessionTranscriptArchive(tmp_path),
        PostgresSessionEvidence(db_pool),
        AgenticNativeSessionEvidence(),
    )
    saved = await restarted.handle(request)
    assert saved.evidence_watermark == 6
    assert await archive.get(saved.archive) == request.content
    snapshot = await BuildInventorySnapshotHandler(
        journal,
        inventory,
        max_evidence_records=5000,
        max_evidence_batches=10,
    ).handle(
        ReconciliationRequest(
            run=run,
            evidence_watermark=saved.evidence_watermark,
            expected_head=None,
            snapshot_id=uuid4(),
            resolver_version=RESOLVER_VERSION,
        )
    )
    await inventory.publish(run, snapshot.snapshot_id, None)
    assert snapshot.counts.edge == 1103
    assert snapshot.counts.node == 1104
    assert snapshot.counts.capture == 1
    after = -1
    total = 0
    while True:
        page = await inventory.page(run, snapshot.snapshot_id, "edge", after=after, limit=137)
        total += len(page.items)
        if page.next_after is None:
            break
        after = page.next_after
    assert total == 1103


async def test_persisted_child_intent_reopens_older_seal_without_native_capture(
    db_pool: asyncpg.Pool,
) -> None:
    run = RunIdentity(source_instance_id=f"child-coverage-{uuid4()}", execution_id="run")
    journal = PostgresSessionEvidence(db_pool)
    inventory = PostgresSessionInventory(db_pool)
    await journal.ensure_ready()
    root, child = tuple(
        InventoryNodeRef(
            kind="invocation", source_instance_id=run.source_instance_id, local_id=name
        )
        for name in ("root", "child")
    )
    await journal.append(
        EvidenceBatch(
            batch_id="host",
            producer_id="host",
            evidence=SessionEvidence(
                run=run,
                memberships=(
                    MembershipEvidence(
                        node=root,
                        run=run,
                        phase_id="phase",
                        attempt_id="attempt",
                        confidence=EvidenceClass.REGISTERED,
                        evidence=reference("host"),
                    ),
                ),
                coverage_contract=CoverageContract(
                    contract_id="supported/1",
                    expected_nodes=(root,),
                    sealed=True,
                ),
            ),
        )
    )
    handler = BuildInventorySnapshotHandler(
        journal, inventory, max_evidence_records=100, max_evidence_batches=100
    )
    request = ReconciliationRequest(
        run=run,
        evidence_watermark=1,
        expected_head=None,
        snapshot_id=uuid4(),
        resolver_version=RESOLVER_VERSION,
    )
    first = await handler.handle(request)
    assert first.coverage.expected_count == 1
    assert first.coverage.state is CoverageState.MISSING
    await inventory.publish(run, first.snapshot_id, None)
    await journal.append(
        EvidenceBatch(
            batch_id="child",
            producer_id="workspace",
            evidence=SessionEvidence(
                run=run,
                invocation_contexts=(
                    InvocationContextEvidence(
                        controller=root,
                        child=child,
                        attempt_id="attempt",
                        evidence=reference("child-intent"),
                    ),
                ),
            ),
        )
    )
    # Re-create the reader so this proof depends on durable evidence, not memory.
    restored = BuildInventorySnapshotHandler(
        PostgresSessionEvidence(db_pool),
        inventory,
        max_evidence_records=100,
        max_evidence_batches=100,
    )
    second = await restored.handle(
        request.model_copy(
            update={
                "evidence_watermark": 2,
                "expected_head": first.snapshot_id,
                "snapshot_id": uuid4(),
            }
        )
    )
    assert second.coverage.expected_count == 2
    assert second.coverage.state is CoverageState.OPEN
    assert set(second.coverage.missing_keys) == {root.key, child.key}
    await inventory.publish(run, second.snapshot_id, first.snapshot_id)
    page = await inventory.page(run, second.snapshot_id, "gap")
    assert any(
        isinstance(item, InventoryGap) and child.key in item.node_keys for item in page.items
    )
    old = await inventory.page(run, first.snapshot_id, "node")
    assert old.snapshot.coverage.expected_count == 1
    assert old.snapshot.coverage.state is CoverageState.MISSING
