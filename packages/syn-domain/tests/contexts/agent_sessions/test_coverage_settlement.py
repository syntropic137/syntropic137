"""Host-side seal: coverage reconciles only when every known node settles (#1398).

The table enumerates the state space: each row is one kind of node or claim a
run can contain, resolved while running, after the execution ends, and after
the bounded settlement deadline. The invariant check after it holds for every
row: ``reconciled`` never coexists with an unaccounted, unsettled, unresolved
or conflicting fact.
"""

from collections.abc import Callable
from itertools import permutations

import pytest

from syn_domain.contexts.agent_sessions import EvidenceBatch, UnsupportedEvidenceIssue
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
    ResolvedInventory,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.services.gap_reasons import (
    CONFLICT_REASONS,
    GapReason,
)
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    resolve_relationships,
)

pytestmark = pytest.mark.unit
RUN = RunIdentity(source_instance_id="source", execution_id="run")
HASH = "a" * 64
OPEN, RECONCILED, MISSING = CoverageState.OPEN, CoverageState.RECONCILED, CoverageState.MISSING
CONFLICTING, UNSUPPORTED = CoverageState.CONFLICTING, CoverageState.UNSUPPORTED
UNKNOWN = CoverageState.UNKNOWN


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


def platform(name: str) -> InventoryNodeRef:
    return InventoryNodeRef(kind="platform", source_instance_id="source", local_id=name)


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


def own_receipt(
    node: InventoryNodeRef, availability: BodyAvailability, sequence: int = 1
) -> CaptureEvidence:
    """A receipt on an owner-covered node itself, from its own producer."""
    return CaptureEvidence(
        node=node,
        availability=availability,
        receipt_sequence=sequence,
        evidence=proof(f"own-{node.local_id}-{sequence}", "own-capture"),
        archived_byte_hash=HASH if availability is BodyAvailability.PRESENT else None,
    )


SESSION = platform("session")
PENDING_SESSION = own_receipt(SESSION, BodyAvailability.PENDING)


def spawn(parent: str, child: str, confidence: EvidenceClass) -> LineageEvidence:
    return LineageEvidence(
        parent=transcript(parent),
        child=transcript(child),
        relation="spawn",
        confidence=confidence,
        evidence=proof(f"edge-{parent}-{child}", "capture"),
    )


def settlement(*stages: RunSettlementStage) -> tuple[RunSettlementEvidence, ...]:
    return tuple(
        RunSettlementEvidence(stage=stage, evidence=proof(f"settle-{stage}", "settlement"))
        for stage in stages
    )


TERMINAL = settlement(RunSettlementStage.EXECUTION_TERMINAL)
DEADLINE = settlement(RunSettlementStage.EXECUTION_TERMINAL, RunSettlementStage.SETTLEMENT_DEADLINE)


def host_run() -> SessionEvidence:
    """What the host projector records for one registered, finished invocation.

    As in ``invocation_evidence``, one host record names both the invocation
    and its platform session, so the platform session needs no body of its own.
    """
    record = proof("registered")
    return SessionEvidence(
        run=RUN,
        memberships=tuple(
            MembershipEvidence(
                node=node,
                run=RUN,
                phase_id="phase",
                attempt_id="attempt",
                confidence=EvidenceClass.REGISTERED,
                evidence=record,
            )
            for node in (ROOT, platform("session"))
        ),
        bindings=(binding(ROOT, "root-native"),),
        invocation_lifecycle=(lifecycle(ROOT, 1, "launched"), lifecycle(ROOT, 2, "completed")),
        captures=(capture("root-native"),),
        coverage_contract=CoverageContract(
            contract_id="syntropic-invocations/1", expected_nodes=(ROOT,), sealed=False
        ),
    )


Change = Callable[[SessionEvidence], SessionEvidence]


def add(**extra: tuple[object, ...]) -> Change:
    def apply(evidence: SessionEvidence) -> SessionEvidence:
        return evidence.model_copy(
            update={name: (*getattr(evidence, name), *items) for name, items in extra.items()}
        )

    return apply


def replace(**fields: object) -> Change:
    return lambda evidence: evidence.model_copy(update=fields)


def child(attempt: str = "attempt") -> Change:
    return add(
        invocation_contexts=(
            InvocationContextEvidence(
                controller=ROOT, child=CHILD, attempt_id=attempt, evidence=proof("ctx", "workspace")
            ),
        ),
        bindings=(binding(CHILD, "child-native"),),
    )


CHILD_SETTLED = add(
    invocation_lifecycle=(lifecycle(CHILD, 1, "launched"), lifecycle(CHILD, 2, "completed")),
    captures=(capture("child-native"),),
)
LEGACY_PLATFORM = add(
    memberships=(
        MembershipEvidence(
            node=platform("legacy"),
            run=RUN,
            phase_id="phase",
            confidence=EvidenceClass.REGISTERED,
            evidence=proof("session-started"),
        ),
    )
)

# name, changes, (while running, execution terminal, after deadline)
STATES: list[tuple[str, tuple[Change, ...], tuple[CoverageState, ...]]] = [
    ("baseline", (), (OPEN, RECONCILED, RECONCILED)),
    (
        "root still running",
        (replace(invocation_lifecycle=(lifecycle(ROOT, 1, "launched"),)),),
        (OPEN, OPEN, MISSING),
    ),
    ("root without any outcome", (replace(invocation_lifecycle=()),), (OPEN, OPEN, MISSING)),
    (
        "root capture pending",
        (replace(captures=(capture("root-native", BodyAvailability.PENDING),)),),
        (OPEN, OPEN, MISSING),
    ),
    ("root never captured", (replace(captures=()),), (OPEN, OPEN, MISSING)),
    (
        "root capture settled missing",
        (replace(captures=(capture("root-native", BodyAvailability.MISSING),)),),
        (OPEN, MISSING, MISSING),
    ),
    (
        "root launch failed",
        (replace(invocation_lifecycle=(lifecycle(ROOT, 1, "launch_failed"),), captures=()),),
        (OPEN, MISSING, MISSING),
    ),
    (
        "root transport failed before announce",
        (replace(invocation_lifecycle=(lifecycle(ROOT, 1, "failed"),), bindings=(), captures=()),),
        (OPEN, OPEN, MISSING),
    ),
    (
        "root launched then failed uncaptured",
        (
            replace(
                invocation_lifecycle=(lifecycle(ROOT, 1, "launched"), lifecycle(ROOT, 2, "failed")),
                bindings=(),
                captures=(),
            ),
        ),
        (OPEN, OPEN, MISSING),
    ),
    (
        "background child running",
        (child(), add(invocation_lifecycle=(lifecycle(CHILD, 1, "launched"),))),
        (OPEN, OPEN, MISSING),
    ),
    ("background child settled", (child(), CHILD_SETTLED), (OPEN, RECONCILED, RECONCILED)),
    ("unverified child attempt", (child("stale"), CHILD_SETTLED), (OPEN, OPEN, MISSING)),
    (
        "conflicting child attempts",
        (
            child(),
            CHILD_SETTLED,
            add(
                invocation_contexts=(
                    InvocationContextEvidence(
                        controller=ROOT,
                        child=CHILD,
                        attempt_id="other",
                        evidence=proof("ctx-other", "workspace"),
                    ),
                )
            ),
        ),
        (CONFLICTING, CONFLICTING, CONFLICTING),
    ),
    (
        "native child uncaptured",
        (add(edges=(spawn("root-native", "native-child", EvidenceClass.CORROBORATED),)),),
        (OPEN, OPEN, MISSING),
    ),
    (
        "native child captured",
        (
            add(
                edges=(spawn("root-native", "native-child", EvidenceClass.CORROBORATED),),
                captures=(capture("native-child"),),
            ),
        ),
        (OPEN, RECONCILED, RECONCILED),
    ),
    (
        "native child parentage unresolved",
        (
            add(
                edges=(spawn("root-native", "native-child", EvidenceClass.CANDIDATE),),
                captures=(capture("native-child"),),
            ),
        ),
        (OPEN, OPEN, CONFLICTING),
    ),
    (
        "conflicting native edge",
        (
            add(
                edges=(spawn("root-native", "native-child", EvidenceClass.CONFLICTING),),
                captures=(capture("native-child"),),
            ),
        ),
        (CONFLICTING, CONFLICTING, CONFLICTING),
    ),
    (
        "two competing parents",
        (
            add(
                edges=(
                    spawn("root-native", "native-child", EvidenceClass.CORROBORATED),
                    spawn("other-parent", "native-child", EvidenceClass.CORROBORATED),
                ),
                captures=(capture("native-child"), capture("other-parent")),
            ),
        ),
        (CONFLICTING, CONFLICTING, CONFLICTING),
    ),
    (
        "conflicting process outcomes",
        (
            replace(
                invocation_lifecycle=(
                    lifecycle(ROOT, 1, "completed"),
                    lifecycle(ROOT, 1, "launch_failed", "other-host"),
                )
            ),
        ),
        (CONFLICTING, CONFLICTING, CONFLICTING),
    ),
    ("platform session without invocation", (LEGACY_PLATFORM,), (OPEN, OPEN, MISSING)),
    # Owner-covered nodes lose their exemption once they carry evidence of their own.
    (
        "owner-covered platform receipt pending",
        (add(captures=(PENDING_SESSION,)),),
        (OPEN, OPEN, MISSING),
    ),
    (
        "owner-covered platform receipt failed",
        (add(captures=(own_receipt(SESSION, BodyAvailability.MISSING),)),),
        (OPEN, MISSING, MISSING),
    ),
    (
        "owner-covered platform receipt corrected to present",
        (add(captures=(PENDING_SESSION, own_receipt(SESSION, BodyAvailability.PRESENT, 2))),),
        (OPEN, RECONCILED, RECONCILED),
    ),
    (
        "owner-covered platform receipt retracted",
        (
            add(
                captures=(PENDING_SESSION,),
                retractions=(
                    EvidenceRetraction(
                        target=PENDING_SESSION.evidence,
                        evidence=PENDING_SESSION.evidence.model_copy(
                            update={"evidence_id": "retract-own"}
                        ),
                    ),
                ),
            ),
        ),
        (OPEN, RECONCILED, RECONCILED),
    ),
    (
        "owner-bound transcript receipt pending",
        (add(captures=(own_receipt(transcript("root-native"), BodyAvailability.PENDING, 1),)),),
        (CONFLICTING, CONFLICTING, CONFLICTING),  # Two producers disagree on one body.
    ),
    (
        "owner-bound transcript receipt failed",
        (replace(captures=(own_receipt(transcript("root-native"), BodyAvailability.MISSING),)),),
        (OPEN, MISSING, MISSING),
    ),
    (
        "owner-bound transcript receipt corrected to present",
        (
            replace(
                captures=(
                    own_receipt(transcript("root-native"), BodyAvailability.PENDING, 1),
                    own_receipt(transcript("root-native"), BodyAvailability.PRESENT, 2),
                )
            ),
        ),
        (OPEN, RECONCILED, RECONCILED),
    ),
    (
        "owner-covered platform owns a binding with no body",
        (add(bindings=(binding(SESSION, "session-native"),)),),
        (OPEN, OPEN, MISSING),
    ),
    (
        "captured unbound transcript",
        (add(captures=(capture("stray"),)),),
        (OPEN, RECONCILED, RECONCILED),
    ),
    (
        "unsupported capture mechanism",
        (
            add(
                acquisition_gaps=(
                    AcquisitionGapEvidence(
                        gap=InventoryGap(reason=UnsupportedEvidenceIssue.HARNESS),
                        evidence=proof("gap", "capture"),
                    ),
                )
            ),
        ),
        (UNSUPPORTED, UNSUPPORTED, UNSUPPORTED),
    ),
    (
        "unreadable child journal",
        (
            add(
                acquisition_gaps=(
                    AcquisitionGapEvidence(
                        gap=InventoryGap(reason="child_journal_unreadable"),
                        evidence=proof("read", "journal"),
                    ),
                )
            ),
        ),
        (OPEN, OPEN, MISSING),
    ),
    (
        "no host registration",
        (replace(coverage_contract=None), LEGACY_PLATFORM),
        (UNKNOWN, UNSUPPORTED, UNSUPPORTED),
    ),
]
STAGES = ((), TERMINAL, DEADLINE)


def build(changes: tuple[Change, ...], stage: tuple[RunSettlementEvidence, ...]) -> SessionEvidence:
    evidence = host_run()
    for change in changes:
        evidence = change(evidence)
    return evidence.model_copy(update={"run_settlement": stage})


def _proven_nodes(result: ResolvedInventory) -> set[str]:
    """Independent oracle: which nodes a reconciled revision can vouch for."""
    present = {
        item.node.key for item in result.captures if item.availability is BodyAvailability.PRESENT
    }
    verified = [
        item
        for item in result.bindings
        if item.confidence in (EvidenceClass.REGISTERED, EvidenceClass.CORROBORATED)
    ]
    proven = set(present)
    for item in verified:
        if item.transcript.key in present:
            proven |= {item.owner.key, item.transcript.key}
    for membership in result.memberships:
        if membership.node.kind == "platform":
            records = set(membership.evidence)
            if any(
                other.node.key in proven
                and other.node.kind == "invocation"
                and records & set(other.evidence)
                for other in result.memberships
            ):
                proven.add(membership.node.key)
    return proven


def assert_invariant(result: ResolvedInventory) -> None:
    reasons = {gap.reason for gap in result.gaps}
    if result.coverage.state is RECONCILED:
        assert result.coverage.missing_keys == ()
        assert not reasons & CONFLICT_REASONS
        assert GapReason.UNRESOLVED_PARENTAGE not in reasons
        assert GapReason.UNVERIFIED_CONTEXT not in reasons
        assert GapReason.INVOCATION_RUNNING not in reasons
        # Every node the evidence names is vouched for by a present body.
        assert {node.ref.key for node in result.nodes} <= _proven_nodes(result)
    if reasons & CONFLICT_REASONS and result.coverage.state not in (UNKNOWN, UNSUPPORTED):
        assert result.coverage.state is CONFLICTING


@pytest.mark.parametrize(("name", "changes", "states"), STATES, ids=[row[0] for row in STATES])
def test_coverage_state_space(
    name: str, changes: tuple[Change, ...], states: tuple[CoverageState, ...]
) -> None:
    del name
    for stage, expected in zip(STAGES, states, strict=True):
        result = resolve_relationships(build(changes, stage))
        assert result.coverage.state is expected, stage
        assert_invariant(result)


@pytest.mark.parametrize("stage", STAGES)
def test_transport_failure_before_announce_reads_distinct_from_launched_failure(
    stage: tuple[RunSettlementEvidence, ...],
) -> None:
    """Same coverage, different reason: only the launch fact separates them."""
    never = build(
        (replace(invocation_lifecycle=(lifecycle(ROOT, 1, "failed"),), bindings=(), captures=()),),
        stage,
    )
    ran = build(
        (
            replace(
                invocation_lifecycle=(lifecycle(ROOT, 1, "launched"), lifecycle(ROOT, 2, "failed")),
                bindings=(),
                captures=(),
            ),
        ),
        stage,
    )
    bound = build(
        (replace(invocation_lifecycle=(lifecycle(ROOT, 1, "failed"),), captures=()),), stage
    )
    before = {gap.reason for gap in resolve_relationships(never).gaps}
    after = {gap.reason for gap in resolve_relationships(ran).gaps}
    claimed = {gap.reason for gap in resolve_relationships(bound).gaps}
    assert GapReason.INVOCATION_TRANSPORT_FAILED_BEFORE_ANNOUNCE in before
    assert "invocation_failed" not in before
    assert "invocation_failed" in after
    assert GapReason.INVOCATION_TRANSPORT_FAILED_BEFORE_ANNOUNCE not in after
    # A native id means the agent announced itself: never "before announce".
    assert "invocation_failed" in claimed
    assert GapReason.INVOCATION_TRANSPORT_FAILED_BEFORE_ANNOUNCE not in claimed
    # Not proven never-ran (unlike a signed launch failure): still owes a body.
    assert GapReason.INVOCATION_LAUNCH_FAILED not in before


def test_stuck_invocation_gap_names_the_node_at_the_deadline() -> None:
    stuck = build((child(), add(invocation_lifecycle=(lifecycle(CHILD, 1, "launched"),))), DEADLINE)
    result = resolve_relationships(stuck)
    assert CHILD.key in result.coverage.missing_keys
    unsettled = [gap for gap in result.gaps if gap.reason == GapReason.INVOCATION_UNSETTLED_AT_SEAL]
    assert unsettled == [
        InventoryGap(reason=GapReason.INVOCATION_UNSETTLED_AT_SEAL, node_keys=(CHILD.key,))
    ]
    # The running observation itself is still reported, not rewritten.
    assert GapReason.INVOCATION_RUNNING in {gap.reason for gap in result.gaps}


def test_deadline_gaps_name_each_unresolved_claim() -> None:
    unverified = resolve_relationships(build((child("stale"), CHILD_SETTLED), DEADLINE))
    assert GapReason.CHILD_CONTEXT_UNRESOLVED_AT_SEAL in {g.reason for g in unverified.gaps}
    assert CHILD.key in unverified.coverage.missing_keys
    candidate = resolve_relationships(
        build(
            (
                add(
                    edges=(spawn("root-native", "native-child", EvidenceClass.CANDIDATE),),
                    captures=(capture("native-child"),),
                ),
            ),
            DEADLINE,
        )
    )
    assert GapReason.PARENTAGE_UNRESOLVED_AT_SEAL in {g.reason for g in candidate.gaps}
    legacy = resolve_relationships(build((LEGACY_PLATFORM,), DEADLINE))
    assert platform("legacy").key in legacy.coverage.missing_keys
    assert platform("session").key not in legacy.coverage.missing_keys


def test_uninstrumented_run_is_classified_with_a_named_gap() -> None:
    result = resolve_relationships(
        build((replace(coverage_contract=None), LEGACY_PLATFORM), TERMINAL)
    )
    assert result.coverage.state is UNSUPPORTED
    gaps = [gap for gap in result.gaps if gap.reason == GapReason.NO_HOST_REGISTRATION]
    assert len(gaps) == 1
    assert platform("legacy").key in gaps[0].node_keys


def test_deadline_without_terminal_execution_never_seals() -> None:
    evidence = build((), settlement(RunSettlementStage.SETTLEMENT_DEADLINE))
    assert resolve_relationships(evidence).coverage.state is OPEN


def test_late_child_after_seal_reopens_in_a_new_revision() -> None:
    sealed = resolve_relationships(build((), TERMINAL))
    assert sealed.coverage.state is RECONCILED
    late = resolve_relationships(
        build((child(), add(invocation_lifecycle=(lifecycle(CHILD, 1, "launched"),))), TERMINAL)
    )
    assert late.revision != sealed.revision
    assert late.coverage.state is OPEN
    # root, its captured transcript (own receipt), and the late child.
    assert late.coverage.expected_count == 3
    # The earlier revision is an immutable value; nothing rewrote it.
    assert sealed.coverage.state is RECONCILED
    assert sealed.coverage.expected_count == 2


def test_settlement_is_order_independent_and_survives_corrections() -> None:
    evidence = build((), DEADLINE)
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
    assert resolve_relationships(corrected).coverage.state is RECONCILED


def test_settlement_facts_count_toward_the_batch_quota() -> None:
    with pytest.raises(ValueError, match="500"):
        EvidenceBatch(
            producer_id="p",
            batch_id="b",
            evidence=SessionEvidence(run=RUN, run_settlement=TERMINAL * 501),
        )
