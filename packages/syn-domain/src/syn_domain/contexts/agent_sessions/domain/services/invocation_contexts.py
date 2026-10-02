"""Attribute child observations only through an exact host-registered attempt."""

from collections import defaultdict
from itertools import chain

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    CoverageContract,
    InvocationContextEvidence,
    MembershipEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceClass,
    InventoryGap,
)

from .gap_reasons import GapReason
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
            gaps.append(InventoryGap(reason=GapReason.CONFLICTING_CONTEXT, node_keys=(child_key,)))
            continue
        hosts = registered[next(iter(claims))]
        attribution = {(host.phase_id, host.attempt_id, host.segment) for host in hosts}
        if len(attribution) != 1:
            gaps.append(InventoryGap(reason=GapReason.UNVERIFIED_CONTEXT, node_keys=(child_key,)))
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


def context_coverage(
    contract: CoverageContract | None,
    children: tuple[MembershipEvidence, ...],
    gaps: tuple[InventoryGap, ...],
) -> CoverageContract | None:
    """Durable child intents expand an existing host contract before capture.

    Only the exact registered-attempt join supplies these children. A late
    intent invalidates an older seal; observing its body cannot seal it again.
    A subsequent host contract must explicitly account for that invocation.
    Unverified/conflicting contexts also prevent a claim of complete coverage.
    """
    if contract is None:
        return None
    expected = {ref.key: ref for ref in contract.expected_nodes}
    previous = set(expected)
    expected.update((child.node.key, child.node) for child in children)
    return contract.model_copy(
        update={
            "expected_nodes": tuple(expected[key] for key in sorted(expected)),
            "sealed": contract.sealed and not gaps and set(expected) == previous,
        }
    )
