"""Workspace observations enter the central journal without inventing membership."""

from unittest.mock import AsyncMock

import pytest
from agentic_isolation.child_journal import ChildCall, ChildChange, ChildIntent, ChildPage

from syn_adapters.session_inventory.child_journal import ChildJournalDrain, child_evidence
from syn_domain.contexts.agent_sessions import EvidenceClass, RunIdentity

pytestmark = pytest.mark.unit


def change(sequence: int, native: str | None = None) -> ChildChange:
    return ChildChange(
        sequence=sequence,
        intent=ChildIntent(
            sequence=1,
            child_invocation_id="child-invocation",
            call=ChildCall(
                invocation_id="top",
                attempt_id="attempt",
                harness="codex",
                parent_native_id="parent/\u03b1",
                tool_call_id="call",
            ),
            child_native_id=native,
        ),
    )


def test_child_observation_preserves_immediate_parent_without_membership_or_coverage() -> None:
    run = RunIdentity(source_instance_id="source", execution_id="run")
    intent = child_evidence(change(1), run, "spool")
    binding = child_evidence(change(2, "child/β"), run, "spool")
    assert intent.evidence.memberships == binding.evidence.memberships == ()
    assert intent.evidence.coverage_contract is None
    assert intent.evidence.edges[0].parent.local_id == "parent/\u03b1"
    assert intent.evidence.edges[0].confidence == EvidenceClass.CORROBORATED
    assert intent.evidence.bindings == ()
    assert binding.evidence.bindings[0].transcript.local_id == "child/β"
    assert binding.evidence.bindings[0].owner == intent.evidence.edges[0].child
    assert child_evidence(change(2, "child/β"), run, "spool") == binding
    assert binding.producer_id != child_evidence(change(2, "child/β"), run, "other").producer_id


async def test_page_returns_progress_only_after_every_append_succeeds() -> None:
    run = RunIdentity(source_instance_id="source", execution_id="run")
    reader = AsyncMock()
    reader.page.return_value = ChildPage(
        watermark=2, changes=(change(1), change(2, "child")), next_after=None
    )
    evidence = AsyncMock()
    evidence.append.side_effect = [1, ConnectionError("unavailable")]
    drain = ChildJournalDrain(evidence)
    with pytest.raises(ConnectionError):
        await drain.page(reader, run=run, spool_id="spool", observation_sequence=1)
    first_batches = [call.args[0] for call in evidence.append.await_args_list]
    evidence.append.reset_mock(side_effect=True)
    result = await drain.page(reader, run=run, spool_id="spool", observation_sequence=1)
    assert result.persisted == 2
    assert result.watermark == 2
    assert result.next_after is None
    assert [call.args[0] for call in evidence.append.await_args_list][:-1] == first_batches
    assert not evidence.append.await_args.args[0].evidence.acquisition_statuses[0].failed


def test_central_resolver_reconstructs_depth_three_from_child_journal_changes() -> None:
    from syn_domain.contexts.agent_sessions import SessionEvidence
    from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
        resolve_relationships,
    )

    run = RunIdentity(source_instance_id="source", execution_id="run")
    first = change(1, "child")
    second = ChildChange(
        sequence=2,
        intent=ChildIntent(
            sequence=2,
            child_invocation_id="grandchild-invocation",
            call=ChildCall(
                invocation_id="top",
                attempt_id="attempt",
                harness="codex",
                parent_native_id="child",
                tool_call_id="nested-call",
            ),
            child_native_id="grandchild",
        ),
    )
    batches = [child_evidence(item, run, "spool").evidence for item in (first, second)]
    combined = SessionEvidence(
        run=run,
        nodes=tuple(node for batch in batches for node in batch.nodes),
        edges=tuple(edge for batch in batches for edge in batch.edges),
        bindings=tuple(binding for batch in batches for binding in batch.bindings),
    )
    resolved = resolve_relationships(combined)
    assert {(edge.parent.local_id, edge.child.local_id) for edge in resolved.edges} == {
        ("parent/\u03b1", "child-invocation"),
        ("child", "grandchild-invocation"),
    }
    assert {
        (binding.owner.local_id, binding.transcript.local_id) for binding in resolved.bindings
    } == {
        ("child-invocation", "child"),
        ("grandchild-invocation", "grandchild"),
    }
    assert resolved.memberships == ()
    assert resolved.coverage.state == "unknown"
    assert resolved.captures == ()
    assert (
        resolve_relationships(
            combined.model_copy(
                update={
                    "nodes": combined.nodes[::-1],
                    "edges": combined.edges[::-1],
                    "bindings": combined.bindings[::-1],
                }
            )
        )
        == resolved
    )


async def test_read_failure_is_durable_and_later_recovery_supersedes_it() -> None:
    from syn_domain.contexts.agent_sessions import SessionEvidence
    from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
        resolve_relationships,
    )

    run = RunIdentity(source_instance_id="source", execution_id="run")
    reader, evidence = AsyncMock(), AsyncMock()
    reader.page.side_effect = OSError("private/path/must-not-leak")
    drain = ChildJournalDrain(evidence)
    with pytest.raises(OSError):
        await drain.page(reader, run=run, spool_id="spool", observation_sequence=7)
    failed = evidence.append.await_args.args[0]
    assert "private/path" not in failed.model_dump_json()
    before = resolve_relationships(failed.evidence)
    assert any(gap.reason == "child_journal_unreadable" for gap in before.gaps)
    reader.page.side_effect = None
    reader.page.return_value = ChildPage(watermark=0, changes=(), next_after=None)
    await drain.page(reader, run=run, spool_id="spool", observation_sequence=8)
    recovered = evidence.append.await_args.args[0]
    statuses = (*failed.evidence.acquisition_statuses, *recovered.evidence.acquisition_statuses)
    for order in (statuses, statuses[::-1]):
        after = resolve_relationships(SessionEvidence(run=run, acquisition_statuses=order))
        assert not any(gap.reason == "child_journal_unreadable" for gap in after.gaps)
        assert after.coverage.state == "unknown"
    # A fresh failure after recovery remains visible, even at an unchanged cursor.
    reader.page.side_effect = OSError("unavailable")
    with pytest.raises(OSError):
        await drain.page(reader, run=run, spool_id="spool", observation_sequence=9)
    latest = evidence.append.await_args.args[0]
    result = resolve_relationships(
        SessionEvidence(
            run=run, acquisition_statuses=(*statuses, *latest.evidence.acquisition_statuses)
        )
    )
    assert any(gap.reason == "child_journal_unreadable" for gap in result.gaps)


async def test_success_status_must_be_durable_before_page_acknowledgement() -> None:
    reader, evidence = AsyncMock(), AsyncMock()
    reader.page.return_value = ChildPage(watermark=0, changes=(), next_after=None)
    evidence.append.side_effect = ConnectionError("journal database unavailable")
    with pytest.raises(ConnectionError):
        await ChildJournalDrain(evidence).page(
            reader,
            run=RunIdentity(source_instance_id="source", execution_id="run"),
            spool_id="spool",
            observation_sequence=1,
        )
    assert not evidence.append.await_args.args[0].evidence.acquisition_statuses[0].failed


def test_cross_harness_binding_preserves_both_namespaces() -> None:
    original = change(2, "same-native-id")
    call = original.intent.call.model_copy(update={"target_harness": "claude"})
    cross = original.model_copy(
        update={"intent": original.intent.model_copy(update={"call": call})}
    )
    evidence = child_evidence(
        cross, RunIdentity(source_instance_id="source", execution_id="run"), "spool"
    ).evidence
    assert evidence.edges[0].parent.harness == "codex"
    assert evidence.bindings[0].transcript.harness == "claude"


def test_legacy_evidence_hash_unchanged_by_optional_delegation_fields() -> None:
    import hashlib
    import json

    original = change(2, "child")
    legacy = original.model_dump()
    legacy["intent"].pop("status")
    legacy["intent"].pop("exit_code")
    legacy["intent"]["call"].pop("target_harness")
    digest = hashlib.sha256(
        json.dumps(legacy, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    batch = child_evidence(
        original, RunIdentity(source_instance_id="source", execution_id="run"), "spool"
    )
    assert batch.evidence.nodes[0].evidence.source_revision == digest
