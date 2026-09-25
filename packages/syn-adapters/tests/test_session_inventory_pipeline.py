"""Local-only reconstruction through real archive, journal, resolver and SQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata

from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.postgres_inventory import PostgresSessionInventory
from syn_adapters.session_inventory.postgres_settlements import PostgresSettlementDeadlines
from syn_domain.contexts.agent_sessions import (
    EvidenceBatch,
    HostSessionEvidenceProjector,
    InventoryNotFound,
    InventoryReconciliationSweepEvent,
    InventorySnapshot,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
)
from syn_domain.contexts.agent_sessions.domain.events.SessionInvocationRecordedEvent import (
    SessionInvocationRecordedEvent,
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
from syn_domain.contexts.agent_sessions.domain.services.gap_reasons import GapReason
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    RESOLVER_VERSION,
)
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.BuildInventorySnapshotHandler import (
    BuildInventorySnapshotHandler,
    EvidenceQuotaExceeded,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
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


async def test_child_process_outcome_survives_real_journal_restart(db_pool: asyncpg.Pool) -> None:
    from unittest.mock import AsyncMock

    from agentic_isolation.child_journal import ChildCall, ChildChange, ChildIntent, ChildPage

    from syn_adapters.session_inventory.child_journal import ChildJournalDrain
    from syn_domain.contexts.agent_sessions.domain.services.evidence_assembly import (
        assemble_evidence,
    )
    from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
        resolve_relationships,
    )

    run = RunIdentity(source_instance_id=f"process-{uuid4()}", execution_id="run")
    writer = PostgresSessionEvidence(db_pool)
    await writer.ensure_ready()
    change = ChildChange(
        sequence=1,
        intent=ChildIntent(
            sequence=1,
            child_invocation_id="child",
            child_native_id=None,
            status="launch_failed",
            call=ChildCall(
                invocation_id="root",
                attempt_id="attempt",
                harness="codex",
                parent_native_id="parent",
                tool_call_id="call",
            ),
        ),
    )
    reader = AsyncMock()
    reader.page.return_value = ChildPage(watermark=1, changes=(change,), next_after=None)
    drain = ChildJournalDrain(writer)
    await drain.page(reader, run=run, spool_id="spool", observation_sequence=1)
    first = await writer.watermark(run)
    await drain.page(reader, run=run, spool_id="spool", observation_sequence=1)
    assert await writer.watermark(run) == first
    restarted = PostgresSessionEvidence(db_pool)
    persisted = await restarted.read(run, first)
    normalized = assemble_evidence(run, persisted.items)
    assert len(normalized.invocation_lifecycle) == 1
    assert normalized.invocation_lifecycle[0].status == "launch_failed"
    result = resolve_relationships(normalized)
    assert result.bindings == ()
    assert result.coverage.state is CoverageState.UNKNOWN
    assert "invocation_launch_failed" in {gap.reason for gap in result.gaps}


async def test_host_launch_failure_replays_without_rewriting_identity_batch(
    db_pool: asyncpg.Pool,
) -> None:
    from event_sourcing import EventEnvelope, EventMetadata

    from syn_domain.contexts.agent_sessions import HostSessionEvidenceProjector
    from syn_domain.contexts.agent_sessions.domain.events.SessionInvocationRecordedEvent import (
        SessionInvocationRecordedEvent,
    )
    from syn_domain.contexts.agent_sessions.domain.services.evidence_assembly import (
        assemble_evidence,
    )
    from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
        resolve_relationships,
    )

    run = RunIdentity(source_instance_id=f"host-outcome-{uuid4()}", execution_id="run")
    writer = PostgresSessionEvidence(db_pool)
    await writer.ensure_ready()
    projector = HostSessionEvidenceProjector(writer, run.source_instance_id)
    for sequence, status in enumerate(("registered", "launch_failed"), start=1):
        event = SessionInvocationRecordedEvent.model_validate(
            {
                "session_id": "platform",
                "execution_id": run.execution_id,
                "phase_id": "phase",
                "invocation_id": "invocation",
                "attempt_id": "attempt",
                "harness": "codex",
                "status": status,
            }
        )
        envelope = EventEnvelope(
            event=event,
            metadata=EventMetadata(
                event_id=f"event-{sequence}",
                aggregate_id="platform",
                aggregate_type="AgentSession",
                aggregate_nonce=sequence,
                global_nonce=sequence,
                event_type=SessionInvocationRecordedEvent.event_type,
            ),
        )
        await projector.handle(envelope)
        watermark = await writer.watermark(run)
        await projector.handle(envelope)
        assert await writer.watermark(run) == watermark
    restored = PostgresSessionEvidence(db_pool)
    page = await restored.read(run, await restored.watermark(run))
    assert len(page.items) == 3
    assert page.items[1].batch.evidence.invocation_lifecycle == ()
    result = resolve_relationships(assemble_evidence(run, page.items))
    assert "invocation_launch_failed" in {gap.reason for gap in result.gaps}
    assert result.bindings == ()
    assert result.coverage.state is CoverageState.OPEN


ENDED = datetime(2026, 9, 25, 12, tzinfo=UTC)


def _host_envelope(
    event: DomainEvent, *, event_id: str, nonce: int, aggregate: str, kind: str
) -> EventEnvelope[DomainEvent]:
    return EventEnvelope(
        event=event,
        metadata=EventMetadata(
            event_id=event_id,
            timestamp=ENDED,
            aggregate_id=aggregate,
            aggregate_type="AgentSession",
            aggregate_nonce=nonce,
            global_nonce=nonce,
            event_type=kind,
        ),
    )


@dataclass(frozen=True)
class _HostRun:
    run: RunIdentity
    journal: PostgresSessionEvidence
    projector: HostSessionEvidenceProjector
    builder: BuildInventorySnapshotHandler

    async def snapshot(self, head: UUID | None = None) -> InventorySnapshot:
        return await self.builder.handle(
            ReconciliationRequest(
                run=self.run,
                evidence_watermark=await self.journal.watermark(self.run),
                expected_head=head,
                snapshot_id=uuid4(),
                resolver_version=RESOLVER_VERSION,
            )
        )

    async def terminate(self) -> None:
        event = WorkflowCompletedEvent(
            workflow_id="definition",
            execution_id=self.run.execution_id,
            completed_at=ENDED,
            total_phases=1,
            completed_phases=1,
            total_input_tokens=0,
            total_output_tokens=0,
            total_tokens=0,
            total_duration_seconds=1.0,
            artifact_ids=[],
        )
        await self.projector.handle(
            _host_envelope(
                event,
                event_id="terminal",
                nonce=99,
                aggregate=self.run.execution_id,
                kind=WorkflowCompletedEvent.event_type,
            )
        )

    async def tick(self, at: datetime) -> None:
        await self.projector.handle(
            _host_envelope(
                InventoryReconciliationSweepEvent(observed_at=at),
                event_id=f"tick-{at.isoformat()}",
                nonce=100,
                aggregate="clock",
                kind=InventoryReconciliationSweepEvent.event_type,
            )
        )


async def _host_run(
    db_pool: asyncpg.Pool,
    tmp_path: Path,
    prefix: str,
    statuses: tuple[Literal["registered", "launched", "completed"], ...],
) -> _HostRun:
    run = RunIdentity(source_instance_id=f"{prefix}-{uuid4()}", execution_id="run")
    journal = PostgresSessionEvidence(db_pool)
    await journal.ensure_ready()
    projector = HostSessionEvidenceProjector(
        journal,
        run.source_instance_id,
        settlements=PostgresSettlementDeadlines(db_pool, run.source_instance_id),
        settlement_grace=timedelta(minutes=5),
    )
    for nonce, status in enumerate(statuses, start=1):
        event = SessionInvocationRecordedEvent(
            session_id="platform",
            execution_id=run.execution_id,
            phase_id="phase",
            invocation_id="root",
            attempt_id="attempt",
            harness="claude",
            status=status,
            native_session_id="root-native",
        )
        await projector.handle(
            _host_envelope(
                event,
                event_id=f"invocation-{nonce}",
                nonce=nonce,
                aggregate="platform",
                kind=SessionInvocationRecordedEvent.event_type,
            )
        )
    archive = LocalSessionTranscriptArchive(tmp_path)
    await archive.ensure_ready()
    body = await archive.put(b"root transcript")
    root_native = InventoryNodeRef(
        kind="transcript",
        source_instance_id=run.source_instance_id,
        harness="claude",
        local_id="root-native",
    )
    await journal.append(
        EvidenceBatch(
            batch_id="root-body",
            producer_id="capture",
            evidence=SessionEvidence(
                run=run,
                captures=(
                    CaptureEvidence(
                        node=root_native,
                        availability=BodyAvailability.PRESENT,
                        receipt_sequence=1,
                        evidence=reference("root-body"),
                        archived_byte_hash=body.sha256,
                    ),
                ),
            ),
        )
    )
    builder = BuildInventorySnapshotHandler(
        journal,
        PostgresSessionInventory(db_pool),
        max_evidence_records=500,
        max_evidence_batches=100,
    )
    return _HostRun(run, journal, projector, builder)


async def test_host_seal_reconciles_then_late_child_reopens_new_revision(
    db_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    from agentic_isolation.child_journal import ChildCall, ChildChange, ChildIntent

    from syn_adapters.session_inventory.child_journal import child_evidence

    host = await _host_run(db_pool, tmp_path, "host-seal", ("registered", "launched", "completed"))
    inventory = PostgresSessionInventory(db_pool)
    assert (await host.snapshot()).coverage.state is CoverageState.OPEN
    await host.terminate()
    await host.terminate()  # Replay appends nothing new.
    sealed = await host.snapshot()
    assert sealed.coverage.state is CoverageState.RECONCILED
    assert sealed.coverage.missing_keys == ()
    await inventory.publish(host.run, sealed.snapshot_id, None)
    change = ChildChange(
        sequence=1,
        intent=ChildIntent(
            sequence=1,
            child_invocation_id="background-child",
            child_native_id=None,
            status="launched",
            call=ChildCall(
                invocation_id="root",
                attempt_id="attempt",
                harness="claude",
                parent_native_id="root-native",
                tool_call_id="call",
            ),
        ),
    )
    await host.journal.append(child_evidence(change, host.run, "spool"))
    restarted = _HostRun(host.run, PostgresSessionEvidence(db_pool), host.projector, host.builder)
    reopened = await restarted.snapshot(sealed.snapshot_id)
    assert reopened.coverage.state is CoverageState.OPEN
    assert reopened.coverage.expected_count == 2
    await inventory.publish(host.run, reopened.snapshot_id, sealed.snapshot_id)
    old = await inventory.page(host.run, sealed.snapshot_id, "node")
    assert old.snapshot.coverage.state is CoverageState.RECONCILED
    assert old.snapshot.coverage.expected_count == 1


async def test_host_seal_turns_stuck_invocation_into_missing_after_recorded_deadline(
    db_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    host = await _host_run(db_pool, tmp_path, "host-stuck", ("registered", "launched"))
    await host.terminate()
    await host.tick(ENDED + timedelta(minutes=1))
    assert (await host.snapshot()).coverage.state is CoverageState.OPEN
    await host.tick(ENDED + timedelta(minutes=6))
    watermark = await host.journal.watermark(host.run)
    await host.tick(ENDED + timedelta(minutes=7))  # A settled deadline is not re-released.
    assert await host.journal.watermark(host.run) == watermark
    missing = await _HostRun(
        host.run, PostgresSessionEvidence(db_pool), host.projector, host.builder
    ).snapshot()
    assert missing.coverage.state is CoverageState.MISSING
    root = InventoryNodeRef(
        kind="invocation", source_instance_id=host.run.source_instance_id, local_id="root"
    )
    assert root.key in missing.coverage.missing_keys
    inventory = PostgresSessionInventory(db_pool)
    await inventory.publish(host.run, missing.snapshot_id, None)
    page = await inventory.page(host.run, missing.snapshot_id, "gap")
    assert any(
        isinstance(item, InventoryGap) and item.reason == GapReason.INVOCATION_UNSETTLED_AT_SEAL
        for item in page.items
    )


async def test_replay_under_another_grace_reads_the_durable_deadline(
    db_pool: asyncpg.Pool, tmp_path: Path
) -> None:
    host = await _host_run(db_pool, tmp_path, "host-grace", ("registered", "launched"))
    await host.terminate()
    watermark = await host.journal.watermark(host.run)
    replay = _HostRun(
        host.run,
        host.journal,
        HostSessionEvidenceProjector(
            host.journal,
            host.run.source_instance_id,
            settlements=PostgresSettlementDeadlines(db_pool, host.run.source_instance_id),
            settlement_grace=timedelta(days=3),
        ),
        host.builder,
    )
    # A recomputed deadline would change the terminal batch and be rejected
    # as reused evidence identity; the stored one makes replay a no-op.
    await replay.terminate()
    assert await host.journal.watermark(host.run) == watermark
    await replay.tick(ENDED + timedelta(minutes=6))
    assert (await replay.snapshot()).coverage.state is CoverageState.MISSING
