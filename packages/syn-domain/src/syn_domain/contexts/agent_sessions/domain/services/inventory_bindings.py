"""Resolve identity aliases and derive scoped membership, never native parentage."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    MembershipEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceClass,
    IdentityBinding,
    InventoryGap,
)

from .inventory_resolution import RANK, references

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        IdentityBindingEvidence,
    )


def _reduce(claims: tuple[IdentityBindingEvidence, ...]) -> list[IdentityBinding]:
    groups: dict[str, list[IdentityBindingEvidence]] = defaultdict(list)
    for claim in claims:
        groups[claim.model_dump_json(exclude={"evidence", "confidence"})].append(claim)
    result: list[IdentityBinding] = []
    for key in sorted(groups):
        items = groups[key]
        first = items[0]
        result.append(
            IdentityBinding(
                owner=first.owner,
                transcript=first.transcript,
                segment=first.segment,
                confidence=max((item.confidence for item in items), key=RANK.__getitem__),
                evidence=references(item.evidence for item in items),
            )
        )
    return result


def resolve_bindings(
    claims: tuple[IdentityBindingEvidence, ...],
) -> tuple[tuple[IdentityBinding, ...], tuple[InventoryGap, ...]]:
    result = _reduce(claims)
    owners: dict[str, list[int]] = defaultdict(list)
    for index, binding in enumerate(result):
        if RANK[binding.confidence] >= 2:
            owners[binding.owner.key].append(index)
    gaps: list[InventoryGap] = []
    for owner, indices in owners.items():
        identities = {result[i].transcript.key for i in indices}
        if len(identities) < 2:
            continue
        strongest = max(RANK[result[i].confidence] for i in indices)
        winners = {
            result[i].transcript.key for i in indices if RANK[result[i].confidence] == strongest
        }
        for index in indices:
            if len(winners) > 1 or result[index].transcript.key not in winners:
                result[index] = result[index].model_copy(
                    update={"confidence": EvidenceClass.CONFLICTING}
                )
        gaps.append(InventoryGap(reason="conflicting_native_binding", node_keys=(owner,)))
    return tuple(result), tuple(gaps)


def bound_memberships(
    direct: tuple[MembershipEvidence, ...],
    bindings: tuple[IdentityBinding, ...],
) -> tuple[MembershipEvidence, ...]:
    by_owner: dict[str, list[MembershipEvidence]] = defaultdict(list)
    for claim in direct:
        if RANK[claim.confidence] >= 2:
            by_owner[claim.node.key].append(claim)
    derived: list[MembershipEvidence] = []
    for binding in bindings:
        if RANK[binding.confidence] < 2:
            continue
        for owner in by_owner[binding.owner.key]:
            confidence = min((owner.confidence, binding.confidence), key=RANK.__getitem__)
            # Every part of the derivation remains inspectable. This does not
            # transfer a transcript's unrelated historical memberships.
            for source in references((owner.evidence, *binding.evidence)):
                derived.append(
                    MembershipEvidence(
                        node=binding.transcript,
                        run=owner.run,
                        phase_id=owner.phase_id,
                        attempt_id=owner.attempt_id,
                        segment=binding.segment,
                        confidence=confidence,
                        evidence=source,
                    )
                )
    return (*direct, *derived)
