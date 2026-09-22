"""Normalized references gain authority only through compatible source facts."""

import pytest

from syn_domain.contexts.agent_sessions.domain.read_models.native_session_evidence import (
    NativeRelationshipFact,
    NativeTranscriptFacts,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    NativeTranscriptObservation,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceClass,
    EvidenceReference,
    InventoryNodeRef,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    resolve_relationships,
)

pytestmark = pytest.mark.unit
RUN = RunIdentity(source_instance_id="source", execution_id="run")


def _observation(identity: str, root: str, child: str | None = None) -> NativeTranscriptObservation:
    return NativeTranscriptObservation(
        node=InventoryNodeRef(
            kind="transcript",
            harness="third-harness",
            source_instance_id="source",
            local_id=identity,
        ),
        facts=NativeTranscriptFacts(
            native_id=identity,
            root_native_id=root,
            identity_lines=(1,),
            byte_count=10,
            extractor_version="third-harness/1",
            relationships=(
                NativeRelationshipFact(
                    parent_native_id=identity,
                    child_native_id=child,
                    relation="spawn",
                    basis="parent_call_result",
                    mechanism="structured-call",
                    source_lines=(2, 3),
                ),
            )
            if child
            else (),
        ),
        evidence=EvidenceReference(
            producer_id="capture",
            evidence_id=identity,
            source_revision="bytes-1",
            locator=f"archive:{identity}",
            extractor_version="third-harness/1",
        ),
    )


def test_depth_three_corroboration_is_central_and_body_availability_independent() -> None:
    observations = (
        _observation("a", "a", "b"),
        _observation("b", "a", "c"),
        _observation("c", "a"),
    )
    resolved = resolve_relationships(SessionEvidence(run=RUN, native_transcripts=observations))
    assert {(edge.parent.local_id, edge.child.local_id) for edge in resolved.edges} == {
        ("a", "b"),
        ("b", "c"),
    }
    assert all(edge.confidence == EvidenceClass.CORROBORATED for edge in resolved.edges)
    assert resolved.captures == ()
    assert resolved.coverage.state == "unknown"
    assert (
        resolve_relationships(SessionEvidence(run=RUN, native_transcripts=observations[::-1]))
        == resolved
    )


def test_missing_child_and_conflicting_child_are_distinct_results() -> None:
    parent = _observation("a", "root", "b")
    missing = resolve_relationships(SessionEvidence(run=RUN, native_transcripts=(parent,)))
    assert missing.edges[0].confidence == EvidenceClass.CANDIDATE
    conflict = resolve_relationships(
        SessionEvidence(run=RUN, native_transcripts=(parent, _observation("b", "other-root")))
    )
    assert conflict.edges[0].confidence == EvidenceClass.CONFLICTING
    assert any(gap.reason == "conflicting_source_evidence" for gap in conflict.gaps)


def test_explicit_child_header_cannot_assert_identity_for_another_child() -> None:
    observation = _observation("a", "root", "b")
    fact = observation.facts.relationships[0].model_copy(update={"basis": "child_header"})
    wrong = observation.model_copy(
        update={"facts": observation.facts.model_copy(update={"relationships": (fact,)})}
    )
    resolved = resolve_relationships(SessionEvidence(run=RUN, native_transcripts=(wrong,)))
    assert resolved.edges[0].confidence == EvidenceClass.CONFLICTING
