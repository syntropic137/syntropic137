"""Schema v3 child journal pages through the real AW typed reader (#1398).

Fixtures are the exact ``child_export`` output of the pinned agentic-workspace
session store (see ``fixtures/child_journal/generate.py``). Every v3 field is
carried into evidence and resolved to an explicit, typed outcome; v2 pages
are still accepted.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agentic_isolation.child_journal import WorkspaceChildJournalReader
from agentic_isolation.providers.base import ExecuteResult

from syn_adapters.session_inventory.child_journal import (
    ChildJournalDrain,
    launch_failure_reason,
)
from syn_domain.contexts.agent_sessions import (
    EvidenceBatch,
    EvidenceClass,
    LaunchFailureReason,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    MembershipEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceReference,
    InventoryNodeRef,
)
from syn_domain.contexts.agent_sessions.domain.services.gap_reasons import GapReason
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    resolve_relationships,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "child_journal"
RUN = RunIdentity(source_instance_id="source", execution_id="run")
ROOT = "root-invocation"


def reader(fixture: str) -> WorkspaceChildJournalReader:
    stdout = (FIXTURES / fixture).read_text()

    async def execute(command: str, **_: object) -> ExecuteResult:
        assert "agentic_session_store.child_export" in command
        return ExecuteResult(exit_code=0, stdout=stdout, stderr="", duration_ms=0)

    return WorkspaceChildJournalReader(execute, "/spool/.agentic-session-store/p/children.sqlite")


async def drained(fixture: str) -> list[EvidenceBatch]:
    writer = AsyncMock()
    await ChildJournalDrain(writer).page(
        reader(fixture), run=RUN, spool_id="spool", observation_sequence=1
    )
    return [call.args[0] for call in writer.append.await_args_list]


def host_registration() -> MembershipEvidence:
    """The host's own record of the controlling attempt the journal names."""
    return MembershipEvidence(
        node=InventoryNodeRef(
            kind="invocation", source_instance_id=RUN.source_instance_id, local_id=ROOT
        ),
        run=RUN,
        phase_id="phase",
        attempt_id="attempt-1",
        confidence=EvidenceClass.REGISTERED,
        evidence=EvidenceReference(
            producer_id="host",
            evidence_id="registered",
            source_revision="1",
            locator="host",
            extractor_version="1",
        ),
    )


def combined(batches: list[EvidenceBatch]) -> SessionEvidence:
    parts = [batch.evidence for batch in batches]
    return SessionEvidence(
        run=RUN,
        memberships=(host_registration(),),
        nodes=tuple(item for part in parts for item in part.nodes),
        edges=tuple(item for part in parts for item in part.edges),
        bindings=tuple(item for part in parts for item in part.bindings),
        invocation_contexts=tuple(item for part in parts for item in part.invocation_contexts),
        invocation_lifecycle=tuple(item for part in parts for item in part.invocation_lifecycle),
    )


def by_call(evidence: SessionEvidence) -> dict[str, str]:
    """tool_call_id -> child invocation key, recovered from the fixture page."""
    import json

    page = json.loads((FIXTURES / "v3_native_lifecycle.json").read_text())["page"]
    keys = {edge.child.local_id: edge.child.key for edge in evidence.edges}
    return {
        change["intent"]["call"]["tool_call_id"]: keys[change["intent"]["child_invocation_id"]]
        for change in page["changes"]
    }


async def test_fixture_is_schema_v3_and_the_typed_reader_accepts_it() -> None:
    import json

    assert json.loads((FIXTURES / "v3_native_lifecycle.json").read_text())["schema_version"] == 3
    page = await reader("v3_native_lifecycle.json").page()
    statuses = {change.intent.status for change in page.changes}
    assert {"pending", "launched", "completed", "launch_failed"} <= statuses
    assert any(change.conflict_native_id for change in page.changes)


async def test_every_v3_field_reaches_evidence() -> None:
    evidence = combined(await drained("v3_native_lifecycle.json"))
    keys = by_call(evidence)
    lifecycle: dict[str, list[tuple[str, int | None, LaunchFailureReason | None]]] = {}
    for item in sorted(evidence.invocation_lifecycle, key=lambda i: i.sequence):
        lifecycle.setdefault(item.node.key, []).append((item.status, item.exit_code, item.reason))
    # Native launched/finished: a stop carries no exit status.
    assert lifecycle[keys["native-finished"]] == [
        ("pending", None, None),
        ("launched", None, None),
        ("completed", None, None),
    ]
    assert lifecycle[keys["native-pending"]] == [("pending", None, None)]
    for call, reason in (
        ("native-tool-failed", LaunchFailureReason.NATIVE_TOOL_FAILED),
        ("native-tool-interrupted", LaunchFailureReason.NATIVE_TOOL_INTERRUPTED),
        ("native-hook-watchdog", LaunchFailureReason.HOOK_WATCHDOG),
        ("delegate-sandbox", LaunchFailureReason.CODEX_SANDBOX_UNAVAILABLE),
        ("delegate-unreachable", LaunchFailureReason.CAPTURE_HOOK_UNREACHABLE),
    ):
        assert lifecycle[keys[call]][-1] == ("launch_failed", None, reason), call
    # conflict_native_id: conflicting evidence, never a corroborated binding.
    conflict = {
        (binding.transcript.local_id, binding.confidence)
        for binding in evidence.bindings
        if binding.owner.key == keys["native-conflict"]
    }
    assert conflict == {
        ("native-child-bound", EvidenceClass.CORROBORATED),
        ("native-child-rejected", EvidenceClass.CONFLICTING),
    }
    assert all(
        binding.confidence is not EvidenceClass.CORROBORATED
        for binding in evidence.bindings
        if binding.transcript.local_id == "native-child-rejected"
    )


async def test_v3_resolves_to_explicit_gaps() -> None:
    evidence = combined(await drained("v3_native_lifecycle.json"))
    keys = by_call(evidence)
    resolved = resolve_relationships(evidence)
    gaps: dict[str, set[str]] = {}
    for gap in resolved.gaps:
        for key in gap.node_keys:
            gaps.setdefault(key, set()).add(gap.reason)
    assert GapReason.INVOCATION_PENDING in gaps[keys["native-pending"]]
    assert GapReason.INVOCATION_RUNNING not in gaps.get(keys["native-pending"], set())
    assert keys["native-finished"] not in gaps
    for call, reason in (
        ("native-tool-failed", GapReason.LAUNCH_FAILED_NATIVE_TOOL_FAILED),
        ("native-tool-interrupted", GapReason.LAUNCH_FAILED_NATIVE_TOOL_INTERRUPTED),
        ("native-hook-watchdog", GapReason.LAUNCH_FAILED_HOOK_WATCHDOG),
        ("delegate-sandbox", GapReason.LAUNCH_FAILED_CODEX_SANDBOX_UNAVAILABLE),
        ("delegate-unreachable", GapReason.LAUNCH_FAILED_CAPTURE_HOOK_UNREACHABLE),
    ):
        assert gaps[keys[call]] == {reason}, call
    assert GapReason.CONFLICTING_BINDING in gaps[keys["native-conflict"]]
    kept = {
        (binding.transcript.local_id, binding.confidence)
        for binding in resolved.bindings
        if binding.owner.key == keys["native-conflict"]
    }
    assert ("native-child-bound", EvidenceClass.CORROBORATED) in kept
    assert ("native-child-rejected", EvidenceClass.CONFLICTING) in kept


async def test_v2_page_is_still_accepted() -> None:
    import json

    assert json.loads((FIXTURES / "v2_delegate.json").read_text())["schema_version"] == 2
    evidence = combined(await drained("v2_delegate.json"))
    statuses = [
        (i.status, i.exit_code)
        for i in sorted(evidence.invocation_lifecycle, key=lambda i: i.sequence)
    ]
    assert statuses[-1] == ("completed", 0)
    assert {b.transcript.harness for b in evidence.bindings} == {"codex"}
    assert not resolve_relationships(evidence).gaps


def test_unknown_wire_reason_is_a_generic_launch_failure() -> None:
    assert launch_failure_reason(None) is None
    assert launch_failure_reason("hook_watchdog") is LaunchFailureReason.HOOK_WATCHDOG
    assert launch_failure_reason("a_future_reason") is None
