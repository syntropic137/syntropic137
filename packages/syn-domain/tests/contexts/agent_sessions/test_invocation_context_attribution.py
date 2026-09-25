"""Child attribution requires an exact active host invocation/attempt join."""

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    CaptureEvidence,
    CoverageContract,
    IdentityBindingEvidence,
    InvocationContextEvidence,
    MembershipEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    BodyAvailability,
    EvidenceClass,
    EvidenceReference,
    EvidenceRetraction,
    InventoryNodeRef,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    resolve_relationships,
)

pytestmark = pytest.mark.unit
RUN = RunIdentity(source_instance_id="source", execution_id="run")


def proof(name: str, producer: str = "host") -> EvidenceReference:
    return EvidenceReference(
        evidence_id=name,
        producer_id=producer,
        source_revision="1",
        locator=name,
        extractor_version="1",
    )


def node(name: str) -> InventoryNodeRef:
    return InventoryNodeRef(kind="invocation", source_instance_id="source", local_id=name)


def evidence(
    attempt: str = "attempt", confidence: EvidenceClass = EvidenceClass.REGISTERED
) -> SessionEvidence:
    child = node("child")
    return SessionEvidence(
        run=RUN,
        memberships=(
            MembershipEvidence(
                node=node("root"),
                run=RUN,
                phase_id="phase",
                attempt_id="attempt",
                confidence=confidence,
                evidence=proof("registered"),
            ),
        ),
        invocation_contexts=(
            InvocationContextEvidence(
                controller=node("root"),
                child=child,
                attempt_id=attempt,
                evidence=proof("context", "workspace"),
            ),
        ),
        bindings=(
            IdentityBindingEvidence(
                owner=child,
                transcript=InventoryNodeRef(
                    kind="transcript",
                    source_instance_id="source",
                    local_id="native",
                    harness="codex",
                ),
                confidence=EvidenceClass.CORROBORATED,
                evidence=proof("binding", "workspace"),
            ),
        ),
    )


def test_exact_attempt_join_attributes_child_and_bound_native_with_both_proofs() -> None:
    resolved = resolve_relationships(evidence())
    descendants = [item for item in resolved.memberships if item.node.local_id != "root"]
    assert {item.node.local_id for item in descendants} == {"child", "native"}
    assert all(item.phase_id == "phase" and item.attempt_id == "attempt" for item in descendants)
    assert all(item.confidence == EvidenceClass.CORROBORATED for item in descendants)
    assert {p.evidence_id for p in descendants[0].evidence} >= {"context", "registered"}
    assert resolved.coverage.state == "unknown"


@pytest.mark.parametrize(
    "attempt,confidence",
    [("stale", EvidenceClass.REGISTERED), ("attempt", EvidenceClass.CANDIDATE)],
)
def test_unverified_context_never_inherits_host_membership(
    attempt: str, confidence: EvidenceClass
) -> None:
    resolved = resolve_relationships(evidence(attempt, confidence))
    assert len(resolved.memberships) == 1
    assert "unverified_invocation_context" in {gap.reason for gap in resolved.gaps}


def test_conflicting_contexts_do_not_choose_first_or_last() -> None:
    original = evidence()
    other = original.invocation_contexts[0].model_copy(
        update={"attempt_id": "other", "evidence": proof("other", "workspace")}
    )
    combined = original.model_copy(
        update={"invocation_contexts": (*original.invocation_contexts, other)}
    )
    resolved = resolve_relationships(combined)
    assert len(resolved.memberships) == 1
    assert "conflicting_invocation_context" in {gap.reason for gap in resolved.gaps}
    assert (
        resolve_relationships(
            combined.model_copy(update={"invocation_contexts": combined.invocation_contexts[::-1]})
        )
        == resolved
    )


def test_retracting_host_registration_removes_derived_child_membership() -> None:
    original = evidence()
    correction = EvidenceRetraction(target=proof("registered"), evidence=proof("retract"))
    resolved = resolve_relationships(original.model_copy(update={"retractions": (correction,)}))
    assert resolved.memberships == ()


def test_context_survives_journal_serialization_and_assembly() -> None:
    from syn_domain.contexts.agent_sessions import EvidenceBatch, StoredEvidenceBatch
    from syn_domain.contexts.agent_sessions.domain.services.evidence_assembly import (
        assemble_evidence,
    )

    source = evidence()
    batch = EvidenceBatch(batch_id="1", producer_id="producer", evidence=source)
    stored = StoredEvidenceBatch(sequence=1, batch=batch)
    restored = StoredEvidenceBatch.model_validate_json(stored.model_dump_json())
    assembled = assemble_evidence(RUN, (restored,))
    assert assembled.invocation_contexts == source.invocation_contexts
    assert resolve_relationships(assembled) == resolve_relationships(source)


def test_context_records_count_toward_batch_quota() -> None:
    from syn_domain.contexts.agent_sessions import EvidenceBatch

    source = evidence()
    oversized = source.model_copy(update={"invocation_contexts": source.invocation_contexts * 501})
    with pytest.raises(ValueError, match="500"):
        EvidenceBatch(batch_id="1", producer_id="producer", evidence=oversized)


def test_duplicate_context_and_host_delivery_does_not_multiply_derived_claims() -> None:
    from syn_domain.contexts.agent_sessions.domain.services.invocation_contexts import (
        context_memberships,
    )

    original = evidence()
    repeated = original.model_copy(
        update={
            "memberships": original.memberships * 200,
            "invocation_contexts": original.invocation_contexts * 200,
        }
    )
    claims, gaps = context_memberships(repeated)
    assert len(claims) == 2
    assert gaps == ()
    assert resolve_relationships(repeated) == resolve_relationships(original)


def test_ambiguous_registered_phases_cannot_supply_child_attribution() -> None:
    original = evidence()
    other = original.memberships[0].model_copy(
        update={"phase_id": "another-phase", "evidence": proof("other-phase")}
    )
    resolved = resolve_relationships(
        original.model_copy(update={"memberships": (*original.memberships, other)})
    )
    assert all(item.node.local_id == "root" for item in resolved.memberships)
    assert "unverified_invocation_context" in {gap.reason for gap in resolved.gaps}


def test_retracting_workspace_context_keeps_host_membership_only() -> None:
    original = evidence()
    correction = EvidenceRetraction(
        target=proof("context", "workspace"), evidence=proof("retract", "workspace")
    )
    resolved = resolve_relationships(original.model_copy(update={"retractions": (correction,)}))
    assert len(resolved.memberships) == 1
    assert resolved.memberships[0].node.local_id == "root"


def test_child_intent_expands_expected_set_before_native_binding_or_capture() -> None:
    source = evidence().model_copy(
        update={
            "bindings": (),
            "coverage_contract": CoverageContract(
                contract_id="supported/1", expected_nodes=(node("root"),), sealed=True
            ),
        }
    )
    resolved = resolve_relationships(source)
    assert resolved.coverage.expected_count == 2
    assert set(resolved.coverage.missing_keys) == {node("root").key, node("child").key}
    assert resolved.coverage.state == "open"
    assert any(
        gap.reason == "expected_body_unavailable" and node("child").key in gap.node_keys
        for gap in resolved.gaps
    )
    assert resolved.bindings == ()
    repeated = source.model_copy(update={"invocation_contexts": source.invocation_contexts * 3})
    assert resolve_relationships(repeated) == resolved


def test_child_capture_does_not_reseal_contract_that_omitted_its_intent() -> None:
    source = evidence()
    contract = CoverageContract(
        contract_id="supported/1", expected_nodes=(node("root"),), sealed=True
    )
    captured = source.model_copy(
        update={
            "coverage_contract": contract,
            "captures": tuple(
                CaptureEvidence(
                    node=ref,
                    availability=BodyAvailability.PRESENT,
                    archived_byte_hash="0" * 64,
                    receipt_sequence=1,
                    evidence=proof("capture-" + str(index)),
                )
                for index, ref in enumerate((node("root"), source.bindings[0].transcript))
            ),
        }
    )
    resolved = resolve_relationships(captured)
    assert resolved.coverage.expected_count == 2
    assert resolved.coverage.missing_keys == ()
    assert resolved.coverage.state == "open"
    # Only a new host contract accounting for the child can seal this set.
    settled = captured.model_copy(
        update={
            "coverage_contract": contract.model_copy(
                update={"expected_nodes": (node("root"), node("child"))}
            )
        }
    )
    assert resolve_relationships(settled).coverage.state == "reconciled"


def test_unverified_child_context_reopens_contract_and_stays_accountable() -> None:
    source = evidence(attempt="stale").model_copy(
        update={
            "coverage_contract": CoverageContract(
                contract_id="supported/1", expected_nodes=(node("root"),), sealed=True
            )
        }
    )
    resolved = resolve_relationships(source)
    # The unattributed child is known, so it is expected (never silently
    # dropped), but it inherits no phase membership from the stale attempt.
    assert resolved.coverage.expected_count == 2
    assert node("child").key in resolved.coverage.missing_keys
    assert resolved.coverage.state == "open"
    assert "unverified_invocation_context" in {gap.reason for gap in resolved.gaps}
