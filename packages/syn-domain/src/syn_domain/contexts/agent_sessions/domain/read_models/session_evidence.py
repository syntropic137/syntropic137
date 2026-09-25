"""Normalized evidence consumed by the one relationship resolver (#1398).

Harness adapters extract facts. They do not decide execution membership.
Claims retain producer identity so a repeated delivery is not a new fact.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

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


class AcquisitionStatusEvidence(InventoryModel):
    """Host-sequenced acquisition outcome; arrival order cannot override recovery."""

    stream_id: Identifier
    sequence: int = Field(ge=1)
    failed: bool
    reason: Identifier
    evidence: EvidenceReference


class InvocationLifecycleEvidence(InventoryModel):
    """Producer-sequenced invocation outcomes, independent of capture settlement.

    A missing exit code stays unknown (historical host events omit it).
    """

    node: InventoryNodeRef
    sequence: int = Field(ge=1)
    status: Literal["launched", "launch_failed", "completed", "failed", "cancelled"]
    exit_code: int | None = Field(default=None, ge=-255, le=255)
    evidence: EvidenceReference

    @model_validator(mode="after")
    def _outcome(self) -> InvocationLifecycleEvidence:
        if self.node.kind != "invocation":
            raise ValueError("lifecycle observation requires an invocation")
        if self.exit_code is None:
            return self
        expected = {
            "launched": self.exit_code is None,
            "launch_failed": self.exit_code is None,
            "completed": self.exit_code == 0,
            "failed": self.exit_code is not None and self.exit_code > 0,
            "cancelled": self.exit_code is not None and self.exit_code < 0,
        }
        if not expected[self.status]:
            raise ValueError("lifecycle status and exit code disagree")
        return self


class RunSettlementStage(StrEnum):
    """Host facts that bound when coverage may seal (#1364).

    EXECUTION_TERMINAL: the workflow execution reached a terminal status. A
    parent finishing proves nothing about background descendants, so this
    alone seals only once every expected node has also settled.
    SETTLEMENT_DEADLINE: the host's bounded grace after EXECUTION_TERMINAL
    elapsed (passage of time). Anything still unsettled then becomes an
    explicit gap instead of holding coverage open forever.
    """

    EXECUTION_TERMINAL = "execution_terminal"
    SETTLEMENT_DEADLINE = "settlement_deadline"


class RunSettlementEvidence(InventoryModel):
    stage: RunSettlementStage
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
    invocation_lifecycle: tuple[InvocationLifecycleEvidence, ...] = ()
    memberships: tuple[MembershipEvidence, ...] = ()
    edges: tuple[LineageEvidence, ...] = ()
    bindings: tuple[IdentityBindingEvidence, ...] = ()
    captures: tuple[CaptureEvidence, ...] = ()
    coverage_contract: CoverageContract | None = None
    retractions: tuple[EvidenceRetraction, ...] = ()
    acquisition_gaps: tuple[AcquisitionGapEvidence, ...] = ()
    acquisition_statuses: tuple[AcquisitionStatusEvidence, ...] = ()
    native_transcripts: tuple[NativeTranscriptObservation, ...] = ()
    run_settlement: tuple[RunSettlementEvidence, ...] = ()

    @model_validator(mode="after")
    def _scope(self) -> SessionEvidence:
        for claim in self.memberships:
            if claim.run != self.run:
                raise ValueError("membership belongs to another run")
        refs = [claim.node for claim in self.nodes]
        refs.extend(claim.node for claim in self.memberships)
        refs.extend(claim.node for claim in self.captures)
        refs.extend(claim.node for claim in self.invocation_lifecycle)
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
