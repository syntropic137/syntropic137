"""Historical backfill normalization: explicit unknowns, stable receipts, no billing (#1398)."""

from __future__ import annotations

import ast
import hashlib
import random
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from syn_domain.contexts.agent_sessions import (
    ArchivedTranscriptFacts,
    BackfillReceipt,
    BackfillReceiptConflict,
    BackfillSessionInventoryHandler,
    HistoricalAcquisition,
    HistoricalAcquisitionQuotaExceeded,
    HistoryBackfillItem,
    HistoryBackfillLease,
    LegacyCaptureObservation,
    LegacyDelegateAlias,
    ProcessHistoryBackfillQueueHandler,
)
from syn_domain.contexts.agent_sessions.domain.read_models.native_session_evidence import (
    NativeRelationshipFact,
    NativeTranscriptFacts,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    CoverageState,
    EvidenceClass,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.services.evidence_assembly import assemble_evidence
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    resolve_relationships,
)
from syn_domain.contexts.agent_sessions.import_identity import platform_session_id_for
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import StoredEvidenceBatch
from syn_domain.contexts.agent_sessions.slices.backfill_session_inventory.legacy_normalization import (
    plan_receipts,
    qualify,
    receipt_evidence,
)

pytestmark = pytest.mark.unit
RUN = RunIdentity(source_instance_id="source", execution_id="run")
SLICE = (
    Path(__file__).resolve().parents[3]
    / "src/syn_domain/contexts/agent_sessions/slices/backfill_session_inventory"
)


def _facts(
    native: str, *, child: str | None = None, root: str | None = None
) -> NativeTranscriptFacts:
    return NativeTranscriptFacts(
        native_id=native,
        root_native_id=root or native,
        identity_lines=(1,),
        byte_count=10,
        extractor_version="fake/1",
        relationships=(
            NativeRelationshipFact(
                parent_native_id=native,
                child_native_id=child,
                relation="spawn",
                basis="parent_call_result",
                mechanism="fake-call",
                source_lines=(1, 2),
            ),
        )
        if child
        else (),
    )


def _archive(capture: str, facts: NativeTranscriptFacts | None) -> ArchivedTranscriptFacts:
    return ArchivedTranscriptFacts(
        producer_id="capture",
        capture_id=capture,
        harness="fake",
        archive_sha256=hashlib.sha256(capture.encode()).hexdigest(),
        facts=facts,
    )


def _acquisition(*, shuffle: int | None = None, duplicate: bool = False) -> HistoricalAcquisition:
    observations = [
        LegacyCaptureObservation(
            platform_session_id="phase-a",
            phase_id="a",
            observed_at="t1",
            schema_version=2,
            native_session_ids=("root", "child", "unknown"),
        ),
        LegacyCaptureObservation(
            platform_session_id="phase-b", phase_id="b", observed_at="t2", schema_version=1
        ),
    ]
    archives = [
        _archive("root", _facts("root", child="child")),
        _archive("child", _facts("child", root="root")),
    ]
    aliases = [LegacyDelegateAlias(native_session_id="root")]
    if duplicate:
        observations, archives, aliases = observations * 2, archives * 2, aliases * 2
    if shuffle is not None:
        for items in (observations, archives, aliases):
            random.Random(shuffle).shuffle(items)
    return HistoricalAcquisition(
        run=RUN,
        observations=tuple(observations),
        archives=tuple(archives),
        delegate_aliases=tuple(aliases),
    )


def _resolve(receipts: tuple[BackfillReceipt, ...]):
    batches = [
        StoredEvidenceBatch(sequence=index, batch=receipt_evidence(item))
        for index, item in enumerate(receipts, start=1)
    ]
    return resolve_relationships(assemble_evidence(RUN, batches))


def test_qualification_is_independent_of_order_and_duplicate_delivery() -> None:
    expected = qualify(_acquisition())
    assert qualify(_acquisition(shuffle=7, duplicate=True)) == expected
    snapshot = uuid4()
    assert plan_receipts(RUN, snapshot, qualify(_acquisition(shuffle=3)), ()) == plan_receipts(
        RUN, snapshot, expected, ()
    )


def test_unsupported_and_unqualified_history_stays_explicitly_unknown() -> None:
    resolved = _resolve(plan_receipts(RUN, uuid4(), qualify(_acquisition()), ()))
    reasons = {gap.reason for gap in resolved.gaps}
    assert {"legacy_capture_unsupported", "legacy_native_identity_unqualified"} <= reasons
    assert resolved.coverage.state is CoverageState.UNKNOWN
    assert all(node.ref.local_id != "unknown" for node in resolved.nodes)
    child = next(m for m in resolved.memberships if m.node.local_id == "child")
    assert (child.phase_id, child.confidence) == ("a", EvidenceClass.CANDIDATE)
    edge = resolved.edges[0]
    assert (edge.parent.local_id, edge.child.local_id) == ("root", "child")
    assert edge.confidence is EvidenceClass.CORROBORATED


def test_delegate_alias_keeps_the_fixed_platform_identity() -> None:
    resolved = _resolve(plan_receipts(RUN, uuid4(), qualify(_acquisition()), ()))
    binding = resolved.bindings[0]
    assert binding.owner.local_id == platform_session_id_for("root")
    assert binding.transcript.local_id == "root"
    assert binding.confidence is EvidenceClass.CORROBORATED


def test_known_fingerprints_reuse_receipts_and_new_qualification_supersedes() -> None:
    first_snapshot, second_snapshot = uuid4(), uuid4()
    unqualified = HistoricalAcquisition(
        run=RUN,
        observations=(
            LegacyCaptureObservation(
                platform_session_id="p",
                observed_at="t",
                schema_version=2,
                native_session_ids=("x",),
            ),
        ),
    )
    first = plan_receipts(RUN, first_snapshot, qualify(unqualified), ())
    assert [item.ordinal for item in first] == [1]
    assert plan_receipts(RUN, second_snapshot, qualify(unqualified), first) == ()
    qualified = unqualified.model_copy(update={"archives": (_archive("x", _facts("x")),)})
    second = plan_receipts(RUN, second_snapshot, qualify(qualified, first), first)
    replacement = next(item for item in second if item.record.kind == "capture_observation")
    assert replacement.supersedes == (first[0].reference,)
    resolved = _resolve((*first, *second))
    assert "legacy_native_identity_unqualified" not in {gap.reason for gap in resolved.gaps}
    assert any(m.node.local_id == "x" for m in resolved.memberships)
    # Expired bytes later never un-qualify: prior receipts keep the namespace.
    expired = unqualified.model_copy(update={"archives": (_archive("x", None),)})
    assert all(
        item.record.kind == "archived_transcript"
        for item in plan_receipts(
            RUN, uuid4(), qualify(expired, (*first, *second)), (*first, *second)
        )
    )


async def test_repeated_handler_run_materializes_once_and_retries_a_lost_race() -> None:
    stored: list[BackfillReceipt] = []
    conflicts = [True]

    async def existing(_run: RunIdentity) -> tuple[BackfillReceipt, ...]:
        return tuple(stored)

    async def insert(_run: RunIdentity, items: tuple[BackfillReceipt, ...]) -> None:
        if conflicts:
            conflicts.pop()
            raise BackfillReceiptConflict("race")
        stored.extend(items)

    source, receipts, journal, refresh = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    source.acquire.return_value = _acquisition()
    receipts.existing.side_effect = existing
    receipts.insert.side_effect = insert
    journal.append.return_value = 1
    refresh.handle.return_value = "job"
    handler = BackfillSessionInventoryHandler(source, receipts, journal, refresh)
    first = await handler.handle(RUN, "key")
    second = await handler.handle(RUN, "key")
    assert first.materialized == first.receipts == len(stored) > 0
    assert (second.materialized, second.receipts) == (0, first.receipts)
    appended = [call.args[0] for call in journal.append.await_args_list]
    assert appended[: first.receipts] == appended[first.receipts :]
    assert refresh.handle.await_args.args[1].startswith("session-history-backfill/")


async def test_queue_fails_quota_permanently_and_retries_other_errors() -> None:
    lease = HistoryBackfillLease(
        item=HistoryBackfillItem(run=RUN, idempotency_key="k"), lease_token=1, attempts=1
    )
    queue, backfill = AsyncMock(), AsyncMock()
    queue.claim.side_effect = [lease, lease.model_copy(update={"attempts": 2}), lease, None]
    backfill.handle.side_effect = [
        HistoricalAcquisitionQuotaExceeded("big"),
        RuntimeError("down"),
        RuntimeError("down"),
    ]
    worker = ProcessHistoryBackfillQueueHandler(
        queue, backfill, lease_seconds=5, retry_seconds=1, max_items_per_tick=5, max_attempts=2
    )
    assert await worker.handle() == 0
    assert [call.args[1] for call in queue.fail.await_args_list] == [
        "history_quota_exceeded",
        "history_backfill_failed",
    ]
    queue.retry.assert_awaited_once()
    queue.complete.assert_not_awaited()


def test_backfill_slice_has_no_path_to_pricing_billing_or_import_writes() -> None:
    forbidden = ("delegate_import", "import_ledger", "session_cost", "canonical_totals", "pricing")
    adapters = Path(__file__).resolve().parents[4] / "syn-adapters/src/syn_adapters"
    modules = [*SLICE.glob("*.py"), *(adapters / "session_inventory").glob("history_*.py")]
    assert len(modules) >= 5
    for module in modules:
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(word in node.module for word in forbidden), (module, node.module)
