"""Validate immutable provenance before applying explicit producer corrections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import SessionEvidence

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
        EvidenceReference,
    )

from .inventory_resolution import references


class _Evidenced(Protocol):
    @property
    def evidence(self) -> EvidenceReference: ...


def _retain[T: _Evidenced](claims: tuple[T, ...], revoked: set[tuple[str, str]]) -> tuple[T, ...]:
    return tuple(
        item
        for item in claims
        if (item.evidence.producer_id, item.evidence.evidence_id) not in revoked
    )


def active_evidence(evidence: SessionEvidence) -> SessionEvidence:
    corrections = [ref for item in evidence.retractions for ref in (item.target, item.evidence)]
    originals = [
        claim.evidence
        for group in (
            evidence.nodes,
            evidence.invocation_contexts,
            evidence.invocation_lifecycle,
            evidence.memberships,
            evidence.edges,
            evidence.bindings,
            evidence.captures,
            evidence.acquisition_gaps,
            evidence.acquisition_statuses,
            evidence.native_transcripts,
        )
        for claim in group
    ]
    # Compare against the original before filtering: a correction must not hide
    # conflicting reuse of a producer's immutable evidence identity.
    references((*corrections, *originals))
    revoked = {(item.target.producer_id, item.target.evidence_id) for item in evidence.retractions}
    if not revoked:
        return evidence
    return SessionEvidence(
        run=evidence.run,
        coverage_contract=evidence.coverage_contract,
        retractions=evidence.retractions,
        nodes=_retain(evidence.nodes, revoked),
        invocation_contexts=_retain(evidence.invocation_contexts, revoked),
        invocation_lifecycle=_retain(evidence.invocation_lifecycle, revoked),
        memberships=_retain(evidence.memberships, revoked),
        edges=_retain(evidence.edges, revoked),
        bindings=_retain(evidence.bindings, revoked),
        captures=_retain(evidence.captures, revoked),
        acquisition_gaps=_retain(evidence.acquisition_gaps, revoked),
        acquisition_statuses=_retain(evidence.acquisition_statuses, revoked),
        native_transcripts=_retain(evidence.native_transcripts, revoked),
    )
