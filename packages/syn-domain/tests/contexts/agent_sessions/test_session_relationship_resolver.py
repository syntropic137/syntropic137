"""Behavioral reconstruction cases independent of any harness parser (#1398)."""

from __future__ import annotations

from itertools import permutations

import pytest
from pydantic import ValidationError

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    CaptureEvidence,
    CoverageContract,
    LineageEvidence,
    MembershipEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    BodyAvailability,
    CoverageState,
    EvidenceClass,
    EvidenceReference,
    InventoryNodeRef,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    resolve_relationships,
)

pytestmark = pytest.mark.unit
RUN = RunIdentity(source_instance_id="installation-a", execution_id="run-1")


def node(name: str, harness: str = "fake") -> InventoryNodeRef:
    return InventoryNodeRef(
        kind="transcript", source_instance_id=RUN.source_instance_id, local_id=name, harness=harness
    )


def receipt(name: str) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=name,
        producer_id="host",
        source_revision="r1",
        locator=f"records/{name}",
        extractor_version="fake/1",
    )


def edge(
    parent: str, child: str, confidence: EvidenceClass = EvidenceClass.CORROBORATED
) -> LineageEvidence:
    return LineageEvidence(
        parent=node(parent),
        child=node(child),
        relation="spawn",
        confidence=confidence,
        evidence=receipt(f"{parent}-{child}"),
    )


def test_historical_depth_three_without_platform_or_invocation_nodes() -> None:
    result = resolve_relationships(SessionEvidence(run=RUN, edges=(edge("a", "b"), edge("b", "c"))))
    assert {(e.parent.local_id, e.child.local_id) for e in result.edges} == {("a", "b"), ("b", "c")}
    assert all(n.ref.kind == "transcript" for n in result.nodes)
    assert result.coverage.state is CoverageState.UNKNOWN


def test_evidence_order_and_duplicate_delivery_do_not_change_revision() -> None:
    claims = (edge("a", "b"), edge("b", "c"), edge("c", "d"))
    expected = resolve_relationships(SessionEvidence(run=RUN, edges=claims))
    for ordered in permutations(claims):
        actual = resolve_relationships(SessionEvidence(run=RUN, edges=(*ordered, ordered[0])))
        assert actual == expected


def test_registered_parent_survives_conflicting_reconstruction() -> None:
    result = resolve_relationships(
        SessionEvidence(
            run=RUN, edges=(edge("a", "child", EvidenceClass.REGISTERED), edge("other", "child"))
        )
    )
    by_parent = {e.parent.local_id: e.confidence for e in result.edges}
    assert by_parent == {"a": EvidenceClass.REGISTERED, "other": EvidenceClass.CONFLICTING}
    assert any(g.reason == "conflicting_parentage" for g in result.gaps)


def test_equally_supported_parents_remain_conflicting() -> None:
    result = resolve_relationships(SessionEvidence(run=RUN, edges=(edge("a", "c"), edge("b", "c"))))
    assert all(e.confidence is EvidenceClass.CONFLICTING for e in result.edges)


def test_capture_failure_does_not_erase_registered_parentage() -> None:
    result = resolve_relationships(
        SessionEvidence(
            run=RUN,
            edges=(edge("a", "b", EvidenceClass.REGISTERED),),
            coverage_contract=CoverageContract(
                contract_id="supported/1", expected_nodes=(node("b"),), sealed=True
            ),
        )
    )
    assert result.edges[0].confidence is EvidenceClass.REGISTERED
    assert result.coverage.state is CoverageState.MISSING
    assert result.coverage.missing_keys == (node("b").key,)


def test_downloaded_bodies_without_inventory_never_establish_complete_capture() -> None:
    result = resolve_relationships(
        SessionEvidence(
            run=RUN,
            captures=(
                CaptureEvidence(
                    node=node("a"),
                    availability=BodyAvailability.PRESENT,
                    archived_byte_hash="0" * 64,
                    receipt_sequence=1,
                    evidence=receipt("body-a"),
                ),
            ),
        )
    )
    assert result.coverage.state is CoverageState.UNKNOWN


def test_sealed_inventory_requires_every_expected_body() -> None:
    evidence = SessionEvidence(
        run=RUN,
        coverage_contract=CoverageContract(
            contract_id="supported/1", expected_nodes=(node("a"), node("b")), sealed=True
        ),
        captures=tuple(
            CaptureEvidence(
                node=node(n),
                availability=BodyAvailability.PRESENT,
                archived_byte_hash="0" * 64,
                receipt_sequence=1,
                evidence=receipt(n),
            )
            for n in ("a", "b")
        ),
    )
    assert resolve_relationships(evidence).coverage.state is CoverageState.RECONCILED
    assert (
        resolve_relationships(
            evidence.model_copy(update={"captures": evidence.captures[:1]})
        ).coverage.state
        is CoverageState.MISSING
    )


def test_membership_is_many_to_many_without_inventing_parentage() -> None:
    claims = tuple(
        MembershipEvidence(
            node=node("resumed"),
            run=RUN,
            phase_id=p,
            confidence=EvidenceClass.REGISTERED,
            evidence=receipt(p),
        )
        for p in ("research", "build")
    )
    result = resolve_relationships(SessionEvidence(run=RUN, memberships=claims))
    assert {m.phase_id for m in result.memberships} == {"research", "build"}
    assert not result.edges
    assert len(result.nodes) == 1


def test_cycle_marks_only_cycle_edges_not_downstream_or_between_components() -> None:
    claims = tuple(
        edge(a, b).model_copy(update={"relation": "resume"})
        for a, b in (("a", "b"), ("b", "a"), ("b", "c"), ("c", "d"), ("d", "c"), ("d", "e"))
    )
    result = resolve_relationships(SessionEvidence(run=RUN, edges=claims))
    by_pair = {(e.parent.local_id, e.child.local_id): e.confidence for e in result.edges}
    for pair in (("a", "b"), ("b", "a"), ("c", "d"), ("d", "c")):
        assert by_pair[pair] is EvidenceClass.CONFLICTING
    for pair in (("b", "c"), ("d", "e")):
        assert by_pair[pair] is EvidenceClass.CORROBORATED


def test_long_lineage_avoids_python_recursion_limit() -> None:
    result = resolve_relationships(
        SessionEvidence(run=RUN, edges=tuple(edge(str(n), str(n + 1)) for n in range(1100)))
    )
    assert len(result.nodes) == 1101
    assert len(result.edges) == 1100
    assert not result.gaps


def test_capture_receipts_survive_without_an_expected_inventory() -> None:
    capture = CaptureEvidence(
        node=node("a"),
        availability=BodyAvailability.PRESENT,
        archived_byte_hash="0" * 64,
        receipt_sequence=1,
        evidence=receipt("captured"),
    )
    first = resolve_relationships(SessionEvidence(run=RUN, captures=(capture,)))
    expired = capture.model_copy(
        update={
            "availability": BodyAvailability.EXPIRED,
            "receipt_sequence": 2,
            "evidence": receipt("expired"),
        }
    )
    second = resolve_relationships(SessionEvidence(run=RUN, captures=(capture, expired)))
    assert first.captures == (capture,)
    assert first.revision != second.revision
    assert second.coverage.state is CoverageState.UNKNOWN


def test_qualified_identity_prevents_native_id_collisions() -> None:
    a = node("same", "claude")
    b = node("same", "codex")
    other = a.model_copy(update={"source_instance_id": "installation-b"})
    assert len({a.key, b.key, other.key}) == 3
    assert a.local_id == b.local_id == other.local_id == "same"


def test_cross_scope_evidence_is_rejected() -> None:
    other = node("a").model_copy(update={"source_instance_id": "installation-b"})
    with pytest.raises(ValidationError, match="crosses source"):
        SessionEvidence(
            run=RUN,
            memberships=(
                MembershipEvidence(
                    node=other,
                    run=RUN,
                    confidence=EvidenceClass.CANDIDATE,
                    evidence=receipt("foreign"),
                ),
            ),
        )


def test_reused_source_record_identity_cannot_silently_replace_provenance() -> None:
    first = edge("a", "b")
    second = edge("b", "c").model_copy(
        update={"evidence": first.evidence.model_copy(update={"locator": "other"})}
    )
    with pytest.raises(ValueError, match="reused evidence ID"):
        resolve_relationships(SessionEvidence(run=RUN, edges=(first, second)))


def test_lineage_conflicts_do_not_change_independent_capture_coverage() -> None:
    evidence = SessionEvidence(
        run=RUN,
        edges=(edge("a", "child"), edge("b", "child")),
        coverage_contract=CoverageContract(
            contract_id="supported/1", expected_nodes=(node("child"),), sealed=True
        ),
        captures=(
            CaptureEvidence(
                node=node("child"),
                availability=BodyAvailability.PRESENT,
                archived_byte_hash="0" * 64,
                receipt_sequence=1,
                evidence=receipt("body-child"),
            ),
        ),
    )
    result = resolve_relationships(evidence)
    assert result.coverage.state is CoverageState.RECONCILED
    assert all(e.confidence is EvidenceClass.CONFLICTING for e in result.edges)


def test_resumed_segments_of_same_native_transcript_are_not_a_cycle() -> None:
    relation = LineageEvidence(
        parent=node("resumed"),
        child=node("resumed"),
        relation="resume",
        parent_segment="invocation-1",
        child_segment="invocation-2",
        confidence=EvidenceClass.CORROBORATED,
        evidence=receipt("resume"),
    )
    result = resolve_relationships(SessionEvidence(run=RUN, edges=(relation,)))
    assert result.edges[0].confidence is EvidenceClass.CORROBORATED
    assert not result.gaps


def test_explicit_correction_removes_old_claim_but_retains_provenance() -> None:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
        EvidenceRetraction,
    )

    original = edge("wrong-parent", "child")
    corrected = edge("right-parent", "child")
    before = resolve_relationships(SessionEvidence(run=RUN, edges=(original,)))
    retraction = EvidenceRetraction(target=original.evidence, evidence=receipt("correction"))
    after = resolve_relationships(
        SessionEvidence(
            run=RUN,
            edges=(original, corrected),
            retractions=(retraction,),
        )
    )
    assert before.edges[0].parent.local_id == "wrong-parent"
    assert len(after.edges) == 1
    assert after.edges[0].parent.local_id == "right-parent"
    assert after.retractions == (retraction,)
    assert after.revision != before.revision


def test_transcript_producer_cannot_retract_registered_host_binding() -> None:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
        EvidenceRetraction,
    )

    with pytest.raises(ValidationError, match="another producer"):
        EvidenceRetraction(
            target=receipt("host-binding"),
            evidence=receipt("correction").model_copy(update={"producer_id": "transcript"}),
        )


def test_resumed_invocations_share_native_identity_but_keep_phase_memberships() -> None:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        IdentityBindingEvidence,
    )

    owners = tuple(
        InventoryNodeRef(
            kind="invocation",
            source_instance_id=RUN.source_instance_id,
            local_id=f"attempt-{n}",
        )
        for n in range(2)
    )
    bindings = tuple(
        IdentityBindingEvidence(
            owner=owner,
            transcript=node("resumed-native"),
            confidence=EvidenceClass.REGISTERED,
            segment=f"segment-{n}",
            evidence=receipt(f"binding-{n}"),
        )
        for n, owner in enumerate(owners)
    )
    claims = tuple(
        MembershipEvidence(
            node=owner,
            run=RUN,
            phase_id=phase,
            confidence=EvidenceClass.REGISTERED,
            evidence=receipt(phase),
        )
        for owner, phase in zip(owners, ("research", "build"), strict=True)
    )
    result = resolve_relationships(SessionEvidence(run=RUN, bindings=bindings, memberships=claims))
    native = [m for m in result.memberships if m.node.kind == "transcript"]
    assert {(m.phase_id, m.segment) for m in native} == {
        ("research", "segment-0"),
        ("build", "segment-1"),
    }
    assert not result.edges
    assert len(result.bindings) == 2


def test_expected_invocation_body_is_satisfied_by_its_verified_native_binding() -> None:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        IdentityBindingEvidence,
    )

    invocation = InventoryNodeRef(
        kind="invocation", source_instance_id=RUN.source_instance_id, local_id="attempt"
    )
    binding = IdentityBindingEvidence(
        owner=invocation,
        transcript=node("native"),
        confidence=EvidenceClass.REGISTERED,
        evidence=receipt("binding"),
    )
    evidence = SessionEvidence(
        run=RUN,
        bindings=(binding,),
        coverage_contract=CoverageContract(
            contract_id="launch/1", expected_nodes=(invocation,), sealed=True
        ),
        captures=(
            CaptureEvidence(
                node=node("native"),
                availability=BodyAvailability.PRESENT,
                archived_byte_hash="0" * 64,
                receipt_sequence=1,
                evidence=receipt("body"),
            ),
        ),
    )
    assert resolve_relationships(evidence).coverage.state is CoverageState.RECONCILED
    candidate = evidence.model_copy(
        update={"bindings": (binding.model_copy(update={"confidence": EvidenceClass.CANDIDATE}),)}
    )
    assert resolve_relationships(candidate).coverage.missing_keys == (invocation.key,)


def test_conflicting_identity_bindings_do_not_transfer_membership() -> None:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        IdentityBindingEvidence,
    )

    platform = InventoryNodeRef(
        kind="platform", source_instance_id=RUN.source_instance_id, local_id="existing-session"
    )
    evidence = SessionEvidence(
        run=RUN,
        memberships=(
            MembershipEvidence(
                node=platform,
                run=RUN,
                confidence=EvidenceClass.REGISTERED,
                evidence=receipt("membership"),
            ),
        ),
        bindings=tuple(
            IdentityBindingEvidence(
                owner=platform,
                transcript=node(name),
                confidence=EvidenceClass.CORROBORATED,
                evidence=receipt(name),
            )
            for name in ("a", "b")
        ),
    )
    result = resolve_relationships(evidence)
    assert len(result.memberships) == 1
    assert all(binding.confidence is EvidenceClass.CONFLICTING for binding in result.bindings)
    assert result.gaps[0].reason == "conflicting_native_binding"
    assert all(item.ref.kind != "invocation" for item in result.nodes)
