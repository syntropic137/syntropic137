"""Pure claim reduction; authority is not inferred from body availability."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceClass,
    EvidenceReference,
    InventoryGap,
    LineageEdge,
    Membership,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        LineageEvidence,
        MembershipEvidence,
    )

RANK = {
    EvidenceClass.CONFLICTING: 0,
    EvidenceClass.CANDIDATE: 1,
    EvidenceClass.CORROBORATED: 2,
    EvidenceClass.REGISTERED: 3,
}


def references(items: Iterable[EvidenceReference]) -> tuple[EvidenceReference, ...]:
    by_key: dict[tuple[str, str], EvidenceReference] = {}
    for item in items:
        key = (item.producer_id, item.evidence_id)
        previous = by_key.get(key)
        if previous is not None and previous != item:
            raise ValueError("producer reused evidence ID for a different source record")
        by_key[key] = item
    return tuple(by_key[key] for key in sorted(by_key))


def memberships(claims: Iterable[MembershipEvidence]) -> tuple[Membership, ...]:
    groups: dict[str, list[MembershipEvidence]] = defaultdict(list)
    for claim in claims:
        # Encoding the typed value avoids delimiter collisions in opaque IDs.
        key = claim.model_dump_json(exclude={"confidence", "evidence"})
        groups[key].append(claim)
    result: list[Membership] = []
    for key in sorted(groups):
        items = groups[key]
        first = items[0]
        confidence = max((item.confidence for item in items), key=RANK.__getitem__)
        result.append(
            Membership(
                node=first.node,
                run=first.run,
                phase_id=first.phase_id,
                attempt_id=first.attempt_id,
                segment=first.segment,
                confidence=confidence,
                evidence=references(item.evidence for item in items),
            )
        )
    return tuple(result)


def lineage(claims: Iterable[LineageEvidence]) -> tuple[LineageEdge, ...]:
    groups: dict[str, list[LineageEvidence]] = defaultdict(list)
    for claim in claims:
        groups[claim.model_dump_json(exclude={"confidence", "evidence"})].append(claim)
    result: list[LineageEdge] = []
    for key in sorted(groups):
        items = groups[key]
        first = items[0]
        confidence = max((item.confidence for item in items), key=RANK.__getitem__)
        result.append(
            LineageEdge(
                parent=first.parent,
                child=first.child,
                relation=first.relation,
                confidence=confidence,
                parent_segment=first.parent_segment,
                child_segment=first.child_segment,
                evidence=references(item.evidence for item in items),
            )
        )
    return tuple(result)


def resolve_parent_conflicts(
    edges: tuple[LineageEdge, ...],
) -> tuple[tuple[LineageEdge, ...], tuple[InventoryGap, ...]]:
    groups: dict[tuple[str, str | None], list[int]] = defaultdict(list)
    for index, edge in enumerate(edges):
        if edge.relation == "spawn" and RANK[edge.confidence] >= 2:
            groups[(edge.child.key, edge.child_segment)].append(index)
    resolved = list(edges)
    gaps: list[InventoryGap] = []
    for indices in groups.values():
        parent_keys = {(edges[i].parent.key, edges[i].parent_segment) for i in indices}
        if len(parent_keys) < 2:
            continue
        strongest = max(RANK[edges[i].confidence] for i in indices)
        winners = {i for i in indices if RANK[edges[i].confidence] == strongest}
        winning_parents = {(edges[i].parent.key, edges[i].parent_segment) for i in winners}
        rejected = set(indices) if len(winning_parents) > 1 else set(indices) - winners
        for index in rejected:
            resolved[index] = edges[index].model_copy(
                update={"confidence": EvidenceClass.CONFLICTING}
            )
        gaps.append(
            InventoryGap(
                reason="conflicting_parentage",
                node_keys=tuple(sorted({edges[i].child.key for i in indices})),
                evidence_ids=tuple(
                    sorted({ref.evidence_id for i in indices for ref in edges[i].evidence})
                ),
            )
        )
    return tuple(resolved), tuple(gaps)
