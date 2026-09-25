"""Syntropic137's deterministic, source-independent relationship resolver.

No I/O or billing. Historical transcript nodes do not require fabricated
invocations. Revisions describe the acquired evidence, not universal capture.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    BodyAvailability,
    CoverageState,
    EvidenceClass,
    EvidenceReference,
    IdentityBinding,
    InventoryCoverage,
    InventoryGap,
    InventoryNode,
    InventoryNodeRef,
    ResolvedInventory,
)
from syn_domain.contexts.agent_sessions.domain.services.inventory_bindings import (
    bound_memberships,
    resolve_bindings,
)
from syn_domain.contexts.agent_sessions.domain.services.inventory_graph import (
    cyclic_edges,
    edge_endpoints,
)
from syn_domain.contexts.agent_sessions.domain.services.inventory_resolution import (
    lineage,
    memberships,
    references,
    resolve_parent_conflicts,
)

from .acquisition_status import acquisition_gaps
from .coverage_settlement import Settlement, expected_capture_states, settle_coverage

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        SessionEvidence,
    )

from .inventory_corrections import active_evidence
from .invocation_contexts import context_coverage, context_memberships
from .invocation_lifecycle import lifecycle_gaps
from .native_relationships import native_relationships

RESOLVER_VERSION = "syn-session-relationships/8"


def _nodes(evidence: SessionEvidence) -> tuple[InventoryNode, ...]:
    refs: dict[str, InventoryNodeRef] = {}
    origins: dict[str, list[EvidenceReference]] = defaultdict(list)
    for claim in (
        *evidence.nodes,
        *evidence.memberships,
        *evidence.captures,
        *evidence.native_transcripts,
        *evidence.invocation_lifecycle,
    ):
        refs[claim.node.key] = claim.node
        origins[claim.node.key].append(claim.evidence)
    for context in evidence.invocation_contexts:
        for ref in (context.controller, context.child):
            refs[ref.key] = ref
            origins[ref.key].append(context.evidence)
    for edge in evidence.edges:
        for ref in (edge.parent, edge.child):
            refs[ref.key] = ref
            origins[ref.key].append(edge.evidence)
    for binding in evidence.bindings:
        for ref in (binding.owner, binding.transcript):
            refs[ref.key] = ref
            origins[ref.key].append(binding.evidence)
    if evidence.coverage_contract is not None:
        for ref in evidence.coverage_contract.expected_nodes:
            refs[ref.key] = ref
    # Validate producer identities across nodes as well as within one node.
    references(ref for items in origins.values() for ref in items)
    return tuple(
        InventoryNode(ref=refs[key], evidence=references(origins[key])) for key in sorted(refs)
    )


def _coverage_state(
    *, supported: bool, conflicting: bool, sealed: bool, missing: bool
) -> CoverageState:
    if not supported:
        return CoverageState.UNSUPPORTED
    if conflicting:
        return CoverageState.CONFLICTING
    if not sealed:
        return CoverageState.OPEN
    return CoverageState.MISSING if missing else CoverageState.RECONCILED


def _coverage(
    evidence: SessionEvidence, bindings: tuple[IdentityBinding, ...], settlement: Settlement
) -> InventoryCoverage:
    contract = settlement.contract
    if contract is None:
        return InventoryCoverage(state=CoverageState.UNKNOWN)
    expected = {ref.key for ref in contract.expected_nodes}
    states = expected_capture_states(evidence, bindings, expected)
    present = {key for key, values in states.items() if values == {BodyAvailability.PRESENT}}
    missing = tuple(sorted((expected - present) | set(settlement.unsettled_keys)))
    return InventoryCoverage(
        state=_coverage_state(
            supported=contract.supported,
            conflicting=settlement.conflicting or any(len(s) > 1 for s in states.values()),
            sealed=contract.sealed,
            missing=bool(missing or evidence.acquisition_gaps),
        ),
        contract_id=contract.contract_id,
        expected_count=len(expected),
        missing_keys=missing,
    )


def resolve_relationships(evidence: SessionEvidence) -> ResolvedInventory:
    """Resolve a complete acquired evidence set; caller owns paging and commits."""
    evidence = active_evidence(evidence)
    evidence = evidence.model_copy(
        update={
            "acquisition_gaps": (
                *evidence.acquisition_gaps,
                *acquisition_gaps(evidence.acquisition_statuses),
            )
        }
    )
    evidence = evidence.model_copy(
        update={
            "edges": (*evidence.edges, *native_relationships(evidence.native_transcripts)),
        }
    )
    child_memberships, context_gaps = context_memberships(evidence)
    process_gaps = lifecycle_gaps(evidence.invocation_lifecycle)
    evidence = evidence.model_copy(
        update={
            "memberships": (*evidence.memberships, *child_memberships),
            "coverage_contract": context_coverage(
                evidence.coverage_contract, child_memberships, context_gaps
            ),
        }
    )
    bindings, binding_gaps = resolve_bindings(evidence.bindings)
    settlement = settle_coverage(
        evidence, evidence.coverage_contract, bindings, process_gaps, context_gaps
    )
    evidence = evidence.model_copy(update={"coverage_contract": settlement.contract})
    nodes = _nodes(evidence)
    resolved_edges, conflict_gaps = resolve_parent_conflicts(lineage(evidence.edges))
    cycles = cyclic_edges(resolved_edges)
    gaps = [
        *context_gaps,
        *process_gaps,
        *conflict_gaps,
        *binding_gaps,
        *settlement.gaps,
        *(item.gap for item in evidence.acquisition_gaps),
    ]
    if cycles:
        gaps.append(
            InventoryGap(
                reason="lineage_cycle",
                node_keys=tuple(sorted({vertex[0] for pair in cycles for vertex in pair})),
            )
        )
        resolved_edges = tuple(
            edge.model_copy(update={"confidence": EvidenceClass.CONFLICTING})
            if edge_endpoints(edge) in cycles
            else edge
            for edge in resolved_edges
        )
    for edge in resolved_edges:
        if edge.confidence == EvidenceClass.CANDIDATE:
            gaps.append(
                InventoryGap(
                    reason="unresolved_parentage",
                    node_keys=(edge.parent.key, edge.child.key),
                    evidence_ids=tuple(ref.evidence_id for ref in edge.evidence),
                )
            )
    for claim in (*evidence.edges, *evidence.memberships, *evidence.bindings):
        if claim.confidence is EvidenceClass.CONFLICTING:
            gaps.append(
                InventoryGap(
                    reason="conflicting_source_evidence", evidence_ids=(claim.evidence.evidence_id,)
                )
            )
    coverage = _coverage(evidence, bindings, settlement)
    if coverage.missing_keys:
        gaps.append(
            InventoryGap(reason="expected_body_unavailable", node_keys=coverage.missing_keys)
        )
    unique_gaps = {gap.model_dump_json(): gap for gap in gaps}
    result = ResolvedInventory(
        resolver_version=RESOLVER_VERSION,
        run=evidence.run,
        revision="",
        nodes=nodes,
        memberships=memberships(bound_memberships(evidence.memberships, bindings)),
        bindings=bindings,
        edges=resolved_edges,
        gaps=tuple(unique_gaps[key] for key in sorted(unique_gaps)),
        coverage=coverage,
        captures=tuple(sorted(set(evidence.captures), key=lambda item: item.model_dump_json())),
        retractions=tuple(
            sorted(set(evidence.retractions), key=lambda item: item.model_dump_json())
        ),
    )
    revision = hashlib.sha256(result.model_dump_json().encode()).hexdigest()
    return result.model_copy(update={"revision": revision})
