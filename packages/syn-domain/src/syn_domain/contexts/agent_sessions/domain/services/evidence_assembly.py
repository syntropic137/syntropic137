"""Combine a journal prefix without losing historical claims or capture expectations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    AcquisitionGapEvidence,
    AcquisitionStatusEvidence,
    CaptureEvidence,
    CoverageContract,
    IdentityBindingEvidence,
    InvocationContextEvidence,
    LineageEvidence,
    MembershipEvidence,
    NativeTranscriptObservation,
    NodeEvidence,
    SessionEvidence,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
        EvidenceRetraction,
        InventoryNodeRef,
        RunIdentity,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import StoredEvidenceBatch


def assemble_evidence(run: RunIdentity, batches: Iterable[StoredEvidenceBatch]) -> SessionEvidence:
    """Coverage expectations only grow. Latest receipt controls whether capture is sealed.

    The journal prefix is chronological. Corrections retract identified source
    claims explicitly; arrival order never silently replaces historical lineage.
    """
    nodes: list[NodeEvidence] = []
    invocation_contexts: list[InvocationContextEvidence] = []
    acquisition_gaps: list[AcquisitionGapEvidence] = []
    acquisition_statuses: list[AcquisitionStatusEvidence] = []
    native_transcripts: list[NativeTranscriptObservation] = []
    memberships: list[MembershipEvidence] = []
    edges: list[LineageEvidence] = []
    captures: list[CaptureEvidence] = []
    bindings: list[IdentityBindingEvidence] = []
    retractions: list[EvidenceRetraction] = []
    expected: dict[str, InventoryNodeRef] = {}
    contract: CoverageContract | None = None
    supported = True
    previous = 0
    for item in batches:
        if item.sequence != previous + 1:
            raise ValueError("evidence prefix is incomplete or out of order")
        previous = item.sequence
        evidence = item.batch.evidence
        if evidence.run != run:
            raise ValueError("evidence journal crossed run scope")
        nodes.extend(evidence.nodes)
        invocation_contexts.extend(evidence.invocation_contexts)
        acquisition_gaps.extend(evidence.acquisition_gaps)
        acquisition_statuses.extend(evidence.acquisition_statuses)
        native_transcripts.extend(evidence.native_transcripts)
        memberships.extend(evidence.memberships)
        edges.extend(evidence.edges)
        captures.extend(evidence.captures)
        bindings.extend(evidence.bindings)
        retractions.extend(evidence.retractions)
        if evidence.coverage_contract is not None:
            incoming = evidence.coverage_contract
            if contract is not None and incoming.contract_id != contract.contract_id:
                raise ValueError("incompatible capture contracts require explicit reconciliation")
            supported = supported and incoming.supported
            expected.update((ref.key, ref) for ref in incoming.expected_nodes)
            contract = incoming
    if contract is not None:
        contract = contract.model_copy(
            update={
                "expected_nodes": tuple(expected[key] for key in sorted(expected)),
                "supported": supported,
            }
        )
    return SessionEvidence(
        run=run,
        nodes=tuple(nodes),
        invocation_contexts=tuple(invocation_contexts),
        acquisition_gaps=tuple(acquisition_gaps),
        acquisition_statuses=tuple(acquisition_statuses),
        native_transcripts=tuple(native_transcripts),
        memberships=tuple(memberships),
        edges=tuple(edges),
        captures=tuple(captures),
        bindings=tuple(bindings),
        retractions=tuple(retractions),
        coverage_contract=contract,
    )
