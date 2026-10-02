"""Corroborate normalized native references centrally, without harness formats."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import LineageEvidence
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceClass,
    EvidenceReference,
    InventoryNodeRef,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.native_session_evidence import (
        NativeRelationshipFact,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        NativeTranscriptObservation,
    )


def _confidence(
    observation: NativeTranscriptObservation,
    fact: NativeRelationshipFact,
    witnesses: list[NativeTranscriptObservation],
) -> EvidenceClass:
    if fact.basis == "child_header":
        return (
            EvidenceClass.CORROBORATED
            if fact.child_native_id == observation.node.local_id
            else EvidenceClass.CONFLICTING
        )
    if fact.parent_native_id != observation.node.local_id:
        return EvidenceClass.CONFLICTING
    roots = {item.facts.root_native_id for item in witnesses if item.facts.root_native_id}
    if not roots or observation.facts.root_native_id is None:
        return EvidenceClass.CANDIDATE
    return (
        EvidenceClass.CORROBORATED
        if roots == {observation.facts.root_native_id}
        else EvidenceClass.CONFLICTING
    )


def native_relationships(
    observations: tuple[NativeTranscriptObservation, ...],
) -> tuple[LineageEvidence, ...]:
    by_node: dict[str, list[NativeTranscriptObservation]] = defaultdict(list)
    for observation in observations:
        by_node[observation.node.key].append(observation)
    result: list[LineageEvidence] = []
    for observation in observations:
        for fact in observation.facts.relationships:
            parent = InventoryNodeRef(
                kind="transcript",
                source_instance_id=observation.node.source_instance_id,
                harness=observation.node.harness,
                local_id=fact.parent_native_id,
            )
            child = parent.model_copy(update={"local_id": fact.child_native_id})
            witnesses = by_node[child.key]
            confidence = _confidence(observation, fact, witnesses)
            reference = observation.evidence
            fact_key = hashlib.sha256(fact.model_dump_json().encode()).hexdigest()
            proof = EvidenceReference(
                producer_id=reference.producer_id,
                evidence_id=hashlib.sha256(
                    (reference.model_dump_json() + fact_key).encode()
                ).hexdigest(),
                source_revision=reference.source_revision,
                locator="evidence:"
                + hashlib.sha256(reference.model_dump_json().encode()).hexdigest()
                + "#lines="
                + ",".join(map(str, fact.source_lines)),
                extractor_version=reference.extractor_version,
            )
            proofs = [reference, proof]
            if confidence == EvidenceClass.CORROBORATED and fact.basis == "parent_call_result":
                proofs.extend(item.evidence for item in witnesses)
            result.extend(
                LineageEvidence(
                    parent=parent,
                    child=child,
                    relation=fact.relation,
                    confidence=confidence,
                    evidence=origin,
                )
                for origin in proofs
            )
    return tuple(result)
