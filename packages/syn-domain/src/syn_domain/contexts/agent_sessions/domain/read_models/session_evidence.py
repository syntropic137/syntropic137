"""Normalized evidence consumed by the one relationship resolver (#1398).

Harness adapters extract facts. They do not decide execution membership.
Claims retain producer identity so a repeated delivery is not a new fact.
"""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    CaptureReceipt,
    EvidenceClass,
    EvidenceReference,
    EvidenceRetraction,
    Identifier,
    InventoryGap,
    InventoryModel,
    InventoryNodeRef,
    RunIdentity,
)

from .native_session_evidence import NativeTranscriptFacts  # noqa: TC001 - runtime Pydantic field


class NativeTranscriptObservation(InventoryModel):
    node: InventoryNodeRef
    facts: NativeTranscriptFacts
    evidence: EvidenceReference

    @model_validator(mode="after")
    def _identity(self) -> NativeTranscriptObservation:
        if self.node.kind != "transcript" or self.node.local_id != self.facts.native_id:
            raise ValueError("native observation must identify its own transcript")
        return self


class AcquisitionGapEvidence(InventoryModel):
    gap: InventoryGap
    evidence: EvidenceReference


class NodeEvidence(InventoryModel):
    node: InventoryNodeRef
    evidence: EvidenceReference


class MembershipEvidence(InventoryModel):
    node: InventoryNodeRef
    run: RunIdentity
    phase_id: Identifier | None = None
    attempt_id: Identifier | None = None
    segment: Identifier | None = None
    confidence: EvidenceClass
    evidence: EvidenceReference


class LineageEvidence(InventoryModel):
    parent: InventoryNodeRef
    child: InventoryNodeRef
    relation: Literal["spawn", "resume", "fork"]
    confidence: EvidenceClass
    evidence: EvidenceReference
    parent_segment: Identifier | None = None
    child_segment: Identifier | None = None


class IdentityBindingEvidence(InventoryModel):
    owner: InventoryNodeRef
    transcript: InventoryNodeRef
    segment: Identifier | None = None
    confidence: EvidenceClass
    evidence: EvidenceReference

    @model_validator(mode="after")
    def _identity_kinds(self) -> IdentityBindingEvidence:
        if (
            self.owner.kind not in ("platform", "invocation")
            or self.transcript.kind != "transcript"
        ):
            raise ValueError(
                "identity binding requires a platform/invocation owner and a native transcript"
            )
        return self


# The same receipt crosses acquisition, resolution and persistence. A subclass
# would compare unequal after deserializing the public CaptureReceipt schema.
CaptureEvidence = CaptureReceipt


class CoverageContract(InventoryModel):
    """A host-recorded expected set, never inferred from downloaded bodies."""

    contract_id: Identifier
    expected_nodes: tuple[InventoryNodeRef, ...]
    sealed: bool = False
    supported: bool = True


class InvocationContextEvidence(InventoryModel):
    """Workspace claim linking a child to an existing host invocation attempt."""

    controller: InventoryNodeRef
    child: InventoryNodeRef
    attempt_id: Identifier
    evidence: EvidenceReference

    @model_validator(mode="after")
    def _invocation_kinds(self) -> InvocationContextEvidence:
        if self.controller.kind != "invocation" or self.child.kind != "invocation":
            raise ValueError("invocation context requires invocation references")
        if self.controller == self.child:
            raise ValueError("child context cannot reference itself")
        return self


class SessionEvidence(InventoryModel):
    run: RunIdentity
    nodes: tuple[NodeEvidence, ...] = ()
    invocation_contexts: tuple[InvocationContextEvidence, ...] = ()
    memberships: tuple[MembershipEvidence, ...] = ()
    edges: tuple[LineageEvidence, ...] = ()
    bindings: tuple[IdentityBindingEvidence, ...] = ()
    captures: tuple[CaptureEvidence, ...] = ()
    coverage_contract: CoverageContract | None = None
    retractions: tuple[EvidenceRetraction, ...] = ()
    acquisition_gaps: tuple[AcquisitionGapEvidence, ...] = ()
    native_transcripts: tuple[NativeTranscriptObservation, ...] = ()

    @model_validator(mode="after")
    def _scope(self) -> SessionEvidence:
        for claim in self.memberships:
            if claim.run != self.run:
                raise ValueError("membership belongs to another run")
        refs = [claim.node for claim in self.nodes]
        refs.extend(claim.node for claim in self.memberships)
        refs.extend(claim.node for claim in self.captures)
        refs.extend(claim.node for claim in self.native_transcripts)
        for context in self.invocation_contexts:
            refs.extend((context.controller, context.child))
        for edge in self.edges:
            refs.extend((edge.parent, edge.child))
        for binding in self.bindings:
            refs.extend((binding.owner, binding.transcript))
        if self.coverage_contract is not None:
            refs.extend(self.coverage_contract.expected_nodes)
        if any(ref.source_instance_id != self.run.source_instance_id for ref in refs):
            raise ValueError("evidence crosses source namespaces")
        return self
