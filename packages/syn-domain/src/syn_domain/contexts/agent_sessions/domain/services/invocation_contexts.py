"""Attribute child observations only through an exact host-registered attempt."""

from collections import defaultdict
from itertools import chain

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    InvocationContextEvidence,
    MembershipEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceClass,
    InventoryGap,
)

from .inventory_resolution import references


def context_memberships(
    evidence: SessionEvidence,
) -> tuple[tuple[MembershipEvidence, ...], tuple[InventoryGap, ...]]:
    registered: dict[tuple[str, str], list[MembershipEvidence]] = defaultdict(list)
    for membership in evidence.memberships:
        if membership.confidence == EvidenceClass.REGISTERED and membership.attempt_id is not None:
            registered[(membership.node.key, membership.attempt_id)].append(membership)
    groups: dict[str, list[InvocationContextEvidence]] = defaultdict(list)
    for context in evidence.invocation_contexts:
        groups[context.child.key].append(context)
    derived: list[MembershipEvidence] = []
    gaps: list[InventoryGap] = []
    for child_key, contexts in sorted(groups.items()):
        claims = {(item.controller.key, item.attempt_id) for item in contexts}
        if len(claims) != 1:
            gaps.append(
                InventoryGap(reason="conflicting_invocation_context", node_keys=(child_key,))
            )
            continue
        hosts = registered[next(iter(claims))]
        attribution = {(host.phase_id, host.attempt_id, host.segment) for host in hosts}
        if len(attribution) != 1:
            gaps.append(
                InventoryGap(reason="unverified_invocation_context", node_keys=(child_key,))
            )
            continue
        derived.extend(_derive(contexts, hosts, evidence))
    return tuple(derived), tuple(gaps)


def _derive(
    contexts: list[InvocationContextEvidence],
    hosts: list[MembershipEvidence],
    evidence: SessionEvidence,
) -> list[MembershipEvidence]:
    # Repeated host events and hook delivery add provenance, not a Cartesian
    # product of memberships. The caller already proved one attribution.
    host = hosts[0]
    child = contexts[0].child
    proofs = references(
        chain(
            (context.evidence for context in contexts),
            (registered.evidence for registered in hosts),
        )
    )
    return [
        MembershipEvidence(
            node=child,
            run=evidence.run,
            phase_id=host.phase_id,
            attempt_id=host.attempt_id,
            confidence=EvidenceClass.CORROBORATED,
            evidence=proof,
        )
        for proof in proofs
    ]
