"""Host-side seal: coverage settles only after the run and every descendant do (#1398)."""

from itertools import permutations

import pytest

from syn_domain.contexts.agent_sessions import UnsupportedEvidenceIssue
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    AcquisitionGapEvidence,
    CaptureEvidence,
    CoverageContract,
    IdentityBindingEvidence,
    InvocationContextEvidence,
    InvocationLifecycleEvidence,
    LineageEvidence,
    MembershipEvidence,
    RunSettlementEvidence,
    RunSettlementStage,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    BodyAvailability,
    CoverageState,
    EvidenceClass,
    EvidenceReference,
    EvidenceRetraction,
    InventoryGap,
    InventoryNodeRef,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.services.coverage_settlement import (
    CAPTURE_UNSETTLED_AT_SEAL,
    INVOCATION_UNSETTLED_AT_SEAL,
)
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    resolve_relationships,
)

pytestmark = pytest.mark.unit
RUN = RunIdentity(source_instance_id="source", execution_id="run")
HASH = "a" * 64


def proof(name: str, producer: str = "host") -> EvidenceReference:
    return EvidenceReference(
        evidence_id=name,
        producer_id=producer,
        source_revision="1",
        locator=name,
        extractor_version="1",
    )


def invocation(name: str) -> InventoryNodeRef:
    return InventoryNodeRef(kind="invocation", source_instance_id="source", local_id=name)


def transcript(name: str) -> InventoryNodeRef:
    return InventoryNodeRef(
        kind="transcript", source_instance_id="source", local_id=name, harness="claude"
    )


ROOT, CHILD = invocation("root"), invocation("child")


def lifecycle(
    node: InventoryNodeRef, sequence: int, status: str, producer: str = "host-life"
) -> InvocationLifecycleEvidence:
    return InvocationLifecycleEvidence.model_validate(
        {
            "node": node,
            "sequence": sequence,
            "status": status,
            "evidence": proof(f"{node.local_id}-{sequence}-{status}", producer),
        }
    )


def binding(owner: InventoryNodeRef, native: str) -> IdentityBindingEvidence:
    return IdentityBindingEvidence(
        owner=owner,
        transcript=transcript(native),
        confidence=EvidenceClass.REGISTERED,
        evidence=proof(f"bind-{native}"),
    )


def capture(
    native: str, availability: BodyAvailability = BodyAvailability.PRESENT, sequence: int = 1
) -> CaptureEvidence:
    return CaptureEvidence(
        node=transcript(native),
        availability=availability,
        receipt_sequence=sequence,
        evidence=proof(f"capture-{native}-{sequence}", "capture"),
        archived_byte_hash=HASH if availability is BodyAvailability.PRESENT else None,
    )


def settlement(*stages: RunSettlementStage) -> tuple[RunSettlementEvidence, ...]:
    return tuple(
        RunSettlementEvidence(stage=stage, evidence=proof(f"settle-{stage}", "settlement"))
        for stage in stages
    )


TERMINAL = settlement(RunSettlementStage.EXECUTION_TERMINAL)
DEADLINE = settlement(RunSettlementStage.EXECUTION_TERMINAL, RunSettlementStage.SETTLEMENT_DEADLINE)


def host_run(**update: object) -> SessionEvidence:
    """A registered root invocation, as the host contract builder produces it."""
    base = SessionEvidence(
        run=RUN,
        memberships=(
            MembershipEvidence(
                node=ROOT,
                run=RUN,
                phase_id="phase",
                attempt_id="attempt",
                confidence=EvidenceClass.REGISTERED,
                evidence=proof("registered"),
            ),
        ),
        bindings=(binding(ROOT, "root-native"),),
        invocation_lifecycle=(lifecycle(ROOT, 1, "launched"), lifecycle(ROOT, 2, "completed")),
        captures=(capture("root-native"),),
        coverage_contract=CoverageContract(
            contract_id="syntropic-invocations/1", expected_nodes=(ROOT,), sealed=False
        ),
    )
    return base.model_copy(update=update)


def with_child(evidence: SessionEvidence, *extra: object) -> SessionEvidence:
    """A background child registered through the root's exact attempt."""
    context = InvocationContextEvidence(
        controller=ROOT, child=CHILD, attempt_id="attempt", evidence=proof("ctx", "workspace")
    )
    lifecycle_items = tuple(item for item in extra if isinstance(item, InvocationLifecycleEvidence))
    captures = tuple(item for item in extra if isinstance(item, CaptureEvidence))
    return evidence.model_copy(
        update={
            "invocation_contexts": (context,),
            "bindings": (*evidence.bindings, binding(CHILD, "child-native")),
            "invocation_lifecycle": (*evidence.invocation_lifecycle, *lifecycle_items),
            "captures": (*evidence.captures, *captures),
        }
    )


def reasons(evidence: SessionEvidence) -> set[str]:
    return {gap.reason for gap in resolve_relationships(evidence).gaps}


def test_host_contract_stays_open_until_the_execution_is_terminal() -> None:
    assert resolve_relationships(host_run()).coverage.state is CoverageState.OPEN


def test_terminal_run_with_every_expected_body_present_is_reconciled() -> None:
    result = resolve_relationships(host_run(run_settlement=TERMINAL))
    assert result.coverage.state is CoverageState.RECONCILED
    assert result.coverage.missing_keys == ()
    assert result.coverage.contract_id == "syntropic-invocations/1"


def test_terminal_run_with_a_settled_but_absent_body_is_missing() -> None:
    evidence = host_run(
        run_settlement=TERMINAL, captures=(capture("root-native", BodyAvailability.MISSING),)
    )
    result = resolve_relationships(evidence)
    assert result.coverage.state is CoverageState.MISSING
    assert result.coverage.missing_keys == (ROOT.key,)
    assert "expected_body_unavailable" in {gap.reason for gap in result.gaps}


def test_unsupported_capture_mechanism_reports_unsupported_not_missing() -> None:
    gap = AcquisitionGapEvidence(
        gap=InventoryGap(reason=UnsupportedEvidenceIssue.HARNESS), evidence=proof("gap", "capture")
    )
    evidence = host_run(run_settlement=DEADLINE, acquisition_gaps=(gap,))
    assert resolve_relationships(evidence).coverage.state is CoverageState.UNSUPPORTED


def test_conflicting_process_outcomes_report_conflicting_even_after_the_deadline() -> None:
    evidence = host_run(
        run_settlement=DEADLINE,
        invocation_lifecycle=(
            lifecycle(ROOT, 1, "completed"),
            lifecycle(ROOT, 1, "launch_failed", "other-host"),
        ),
    )
    assert resolve_relationships(evidence).coverage.state is CoverageState.CONFLICTING


def test_conflicting_child_context_reports_conflicting() -> None:
    evidence = with_child(host_run(run_settlement=TERMINAL))
    other = evidence.invocation_contexts[0].model_copy(
        update={"attempt_id": "other", "evidence": proof("ctx-other", "workspace")}
    )
    evidence = evidence.model_copy(
        update={"invocation_contexts": (*evidence.invocation_contexts, other)}
    )
    assert resolve_relationships(evidence).coverage.state is CoverageState.CONFLICTING


def test_parent_finishing_does_not_seal_while_a_background_child_runs() -> None:
    running = with_child(host_run(run_settlement=TERMINAL), lifecycle(CHILD, 1, "launched"))
    result = resolve_relationships(running)
    assert result.coverage.state is CoverageState.OPEN
    assert result.coverage.expected_count == 2
    settled = with_child(
        host_run(run_settlement=TERMINAL),
        lifecycle(CHILD, 1, "launched"),
        lifecycle(CHILD, 2, "completed"),
        capture("child-native"),
    )
    assert resolve_relationships(settled).coverage.state is CoverageState.RECONCILED


def test_registered_invocation_without_any_outcome_blocks_the_host_seal() -> None:
    evidence = host_run(run_settlement=TERMINAL, invocation_lifecycle=())
    assert resolve_relationships(evidence).coverage.state is CoverageState.OPEN


def test_pending_capture_blocks_seal_until_the_deadline() -> None:
    pending = (capture("root-native", BodyAvailability.PENDING),)
    assert (
        resolve_relationships(host_run(run_settlement=TERMINAL, captures=pending)).coverage.state
        is CoverageState.OPEN
    )
    result = resolve_relationships(host_run(run_settlement=DEADLINE, captures=pending))
    assert result.coverage.state is CoverageState.MISSING
    assert CAPTURE_UNSETTLED_AT_SEAL in {gap.reason for gap in result.gaps}


def test_stuck_invocation_becomes_an_explicit_gap_at_the_deadline() -> None:
    stuck = with_child(host_run(run_settlement=TERMINAL), lifecycle(CHILD, 1, "launched"))
    assert resolve_relationships(stuck).coverage.state is CoverageState.OPEN
    result = resolve_relationships(stuck.model_copy(update={"run_settlement": DEADLINE}))
    assert result.coverage.state is CoverageState.MISSING
    assert CHILD.key in result.coverage.missing_keys
    unsettled = [gap for gap in result.gaps if gap.reason == INVOCATION_UNSETTLED_AT_SEAL]
    assert unsettled == [InventoryGap(reason=INVOCATION_UNSETTLED_AT_SEAL, node_keys=(CHILD.key,))]
    # The running observation itself is still reported, not rewritten.
    assert "invocation_running" in {gap.reason for gap in result.gaps}


def test_deadline_without_terminal_execution_never_seals() -> None:
    evidence = host_run(run_settlement=settlement(RunSettlementStage.SETTLEMENT_DEADLINE))
    assert resolve_relationships(evidence).coverage.state is CoverageState.OPEN


def test_late_child_after_seal_reopens_in_a_new_revision() -> None:
    sealed = resolve_relationships(host_run(run_settlement=TERMINAL))
    assert sealed.coverage.state is CoverageState.RECONCILED
    late = resolve_relationships(
        with_child(host_run(run_settlement=TERMINAL), lifecycle(CHILD, 1, "launched"))
    )
    assert late.revision != sealed.revision
    assert late.coverage.state is CoverageState.OPEN
    assert late.coverage.expected_count == 2
    # The earlier revision is an immutable value; nothing rewrote it.
    assert sealed.coverage.state is CoverageState.RECONCILED
    assert sealed.coverage.expected_count == 1


def test_late_child_after_deadline_is_a_gap_until_it_settles() -> None:
    late = with_child(host_run(run_settlement=DEADLINE), lifecycle(CHILD, 1, "launched"))
    assert resolve_relationships(late).coverage.state is CoverageState.MISSING
    settled = with_child(
        host_run(run_settlement=DEADLINE),
        lifecycle(CHILD, 1, "launched"),
        lifecycle(CHILD, 2, "completed"),
        capture("child-native"),
    )
    result = resolve_relationships(settled)
    assert result.coverage.state is CoverageState.RECONCILED
    assert INVOCATION_UNSETTLED_AT_SEAL not in {gap.reason for gap in result.gaps}


def test_native_child_of_an_expected_transcript_must_settle_too() -> None:
    edge = LineageEvidence(
        parent=transcript("root-native"),
        child=transcript("native-child"),
        relation="spawn",
        confidence=EvidenceClass.CORROBORATED,
        evidence=proof("native-edge", "capture"),
    )
    open_run = host_run(run_settlement=TERMINAL, edges=(edge,))
    result = resolve_relationships(open_run)
    assert result.coverage.state is CoverageState.OPEN
    assert result.coverage.expected_count == 2
    captured = open_run.model_copy(
        update={"captures": (*open_run.captures, capture("native-child"))}
    )
    assert resolve_relationships(captured).coverage.state is CoverageState.RECONCILED
    expired = resolve_relationships(open_run.model_copy(update={"run_settlement": DEADLINE}))
    assert expired.coverage.state is CoverageState.MISSING
    assert transcript("native-child").key in expired.coverage.missing_keys


def test_conflicting_native_edge_does_not_expand_expectations() -> None:
    edge = LineageEvidence(
        parent=transcript("root-native"),
        child=transcript("native-child"),
        relation="spawn",
        confidence=EvidenceClass.CONFLICTING,
        evidence=proof("native-edge", "capture"),
    )
    result = resolve_relationships(host_run(run_settlement=TERMINAL, edges=(edge,)))
    assert result.coverage.expected_count == 1


def test_launch_failure_settles_without_a_body_and_is_reported_missing() -> None:
    evidence = host_run(
        run_settlement=TERMINAL, invocation_lifecycle=(lifecycle(ROOT, 1, "launch_failed"),)
    )
    result = resolve_relationships(evidence.model_copy(update={"captures": ()}))
    assert result.coverage.state is CoverageState.MISSING
    assert "invocation_launch_failed" in {gap.reason for gap in result.gaps}


def test_unreadable_child_journal_blocks_the_seal_until_the_deadline() -> None:
    gap = AcquisitionGapEvidence(
        gap=InventoryGap(reason="child_journal_unreadable"), evidence=proof("read", "journal")
    )
    assert (
        resolve_relationships(
            host_run(run_settlement=TERMINAL, acquisition_gaps=(gap,))
        ).coverage.state
        is CoverageState.OPEN
    )
    assert (
        resolve_relationships(
            host_run(run_settlement=DEADLINE, acquisition_gaps=(gap,))
        ).coverage.state
        is CoverageState.MISSING
    )


def test_settlement_is_order_independent_and_survives_corrections() -> None:
    evidence = host_run(run_settlement=DEADLINE)
    expected = resolve_relationships(evidence)
    for order in permutations(evidence.run_settlement):
        assert resolve_relationships(evidence.model_copy(update={"run_settlement": order})) == (
            expected
        )
    # An unrelated correction must not drop settlement facts on the floor.
    target = evidence.captures[0].evidence
    corrected = evidence.model_copy(
        update={
            "captures": (*evidence.captures, capture("root-native", sequence=2)),
            "retractions": (
                EvidenceRetraction(
                    target=target, evidence=target.model_copy(update={"evidence_id": "fix"})
                ),
            ),
        }
    )
    assert resolve_relationships(corrected).coverage.state is CoverageState.RECONCILED


def test_settlement_facts_count_toward_the_batch_quota() -> None:
    from syn_domain.contexts.agent_sessions import EvidenceBatch

    with pytest.raises(ValueError, match="500"):
        EvidenceBatch(
            producer_id="p",
            batch_id="b",
            evidence=SessionEvidence(run=RUN, run_settlement=TERMINAL * 501),
        )
