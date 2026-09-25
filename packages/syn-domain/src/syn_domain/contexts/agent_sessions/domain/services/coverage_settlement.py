"""Host-side coverage seal: descendants and capture settle before completeness (#1364).

Seal rule (pure; evaluated on every reconstruction, so the result is a
function of the acquired evidence and never a mutation of an old revision):

1. Expected nodes are the host contract's registered invocations, children
   attributed through an exact registered attempt (``context_coverage``), and
   every descendant reached from an expected node by a non-conflicting spawn or
   fork edge (child journals and native child relationships). Expansion follows
   identity bindings, so an invocation's native transcript carries its children.
2. An expected node is SETTLED when its process is terminal (an invocation's
   latest lifecycle is completed, failed, cancelled or launch_failed; a native
   transcript child has no separate process) AND its capture is terminal (the
   latest local receipt is not pending, or the launch failed and no body can
   exist). A live acquisition failure (e.g. unreadable child journal) is
   unsettled: more children may exist that the host has not read.
3. The host seals once the execution is terminal AND every expected node is
   settled. A parent finishing is never enough on its own.
4. Bounded settlement: once the host's SETTLEMENT_DEADLINE (a passage-of-time
   fact recorded a configured grace after the terminal event) exists, the
   seal no longer waits. Each still-unsettled node becomes an explicit gap and
   is reported missing. No timestamp is ever used to decide parentage.
5. A later child, lifecycle or receipt yields a new revision whose coverage is
   recomputed: before the deadline an unsettled late child reopens coverage;
   after it, the late child is sealed as an explicit gap until it settles.

An explicitly sealed producer contract keeps its prior meaning: it seals
without the host terminal fact, but never over a still-running invocation
unless the host deadline has passed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions.domain.read_models.native_session_evidence import (
    UnsupportedEvidenceIssue,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    RunSettlementStage,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    BodyAvailability,
    EvidenceClass,
    InventoryGap,
)

from .invocation_contexts import CONFLICTING_CONTEXT
from .invocation_lifecycle import (
    CONFLICTING_LIFECYCLE,
    INVOCATION_LAUNCH_FAILED,
    INVOCATION_RUNNING,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        CoverageContract,
        SessionEvidence,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
        CaptureReceipt,
        IdentityBinding,
        InventoryNodeRef,
    )

INVOCATION_UNSETTLED_AT_SEAL = "invocation_unsettled_at_seal"
CAPTURE_UNSETTLED_AT_SEAL = "capture_unsettled_at_seal"
_DESCENDANT_RELATIONS = frozenset({"spawn", "fork"})
_UNSUPPORTED = frozenset(UnsupportedEvidenceIssue)


@dataclass(frozen=True)
class Settlement:
    contract: CoverageContract | None
    gaps: tuple[InventoryGap, ...] = ()
    unsettled_keys: tuple[str, ...] = ()
    conflicting: bool = False


def capture_aliases(bindings: tuple[IdentityBinding, ...]) -> dict[str, str]:
    return {
        binding.owner.key: binding.transcript.key
        for binding in bindings
        if binding.confidence in (EvidenceClass.REGISTERED, EvidenceClass.CORROBORATED)
    }


def latest_capture_states(receipts: list[CaptureReceipt]) -> set[BodyAvailability]:
    # Sequences are comparable only within one producer's receipt stream.
    latest: dict[str, int] = {}
    for item in receipts:
        producer = item.evidence.producer_id
        latest[producer] = max(latest.get(producer, -1), item.receipt_sequence)
    return {
        item.availability
        for item in receipts
        if item.receipt_sequence == latest[item.evidence.producer_id]
    }


def expected_capture_states(
    evidence: SessionEvidence, bindings: tuple[IdentityBinding, ...], keys: set[str]
) -> dict[str, set[BodyAvailability]]:
    grouped: dict[str, list[CaptureReceipt]] = defaultdict(list)
    for item in evidence.captures:
        if item.destination == "local":
            grouped[item.node.key].append(item)
    aliases = capture_aliases(bindings)
    return {key: latest_capture_states(grouped[aliases.get(key, key)]) for key in keys}


def _descendants(
    evidence: SessionEvidence,
    expected: dict[str, InventoryNodeRef],
    bindings: tuple[IdentityBinding, ...],
) -> dict[str, InventoryNodeRef]:
    owners: dict[str, set[str]] = defaultdict(set)
    for owner, transcript in capture_aliases(bindings).items():
        owners[transcript].add(owner)
    children: dict[str, list[InventoryNodeRef]] = defaultdict(list)
    for edge in evidence.edges:
        if (
            edge.relation in _DESCENDANT_RELATIONS
            and edge.confidence is not EvidenceClass.CONFLICTING
        ):
            children[edge.parent.key].append(edge.child)
    aliases = capture_aliases(bindings)
    result = dict(expected)
    frontier = sorted(result)
    while frontier:  # Bounded: each node key enters the frontier at most once.
        key = frontier.pop()
        for parent in {key, aliases.get(key, key), *owners[key]}:
            for child in children[parent]:
                if child.key not in result:
                    result[child.key] = child
                    frontier.append(child.key)
    return result


def _gap_keys(gaps: tuple[InventoryGap, ...], reason: str) -> set[str]:
    return {key for gap in gaps if gap.reason == reason for key in gap.node_keys}


@dataclass(frozen=True)
class _Unsettled:
    running: frozenset[str]
    process: frozenset[str]
    capture: frozenset[str]


def _unsettled(
    evidence: SessionEvidence,
    expected: dict[str, InventoryNodeRef],
    bindings: tuple[IdentityBinding, ...],
    process_gaps: tuple[InventoryGap, ...],
) -> _Unsettled:
    keys = set(expected)
    running = _gap_keys(process_gaps, INVOCATION_RUNNING) & keys
    # A registered invocation with no outcome at all has not settled either.
    # Only the host seal waits on it; an explicit producer seal predates this.
    observed = {item.node.key for item in evidence.invocation_lifecycle}
    unobserved = {
        key for key, ref in expected.items() if ref.kind == "invocation" and key not in observed
    }
    launch_failed = _gap_keys(process_gaps, INVOCATION_LAUNCH_FAILED)
    states = expected_capture_states(evidence, bindings, keys)
    capture = {
        key
        for key, values in states.items()
        if key not in launch_failed and (not values or BodyAvailability.PENDING in values)
    }
    return _Unsettled(frozenset(running), frozenset(running | unobserved), frozenset(capture))


def _deadline_gaps(unsettled: _Unsettled) -> tuple[InventoryGap, ...]:
    claims = (
        (INVOCATION_UNSETTLED_AT_SEAL, unsettled.process),
        (CAPTURE_UNSETTLED_AT_SEAL, unsettled.capture - unsettled.process),
    )
    return tuple(
        InventoryGap(reason=reason, node_keys=tuple(sorted(keys)))
        for reason, keys in claims
        if keys
    )


def _conflicting(
    keys: set[str], process_gaps: tuple[InventoryGap, ...], context_gaps: tuple[InventoryGap, ...]
) -> bool:
    # A child claimed by incompatible attempts cannot be placed, so it is never
    # expected; its conflict still makes this run's completeness unknowable.
    return bool(_gap_keys(process_gaps, CONFLICTING_LIFECYCLE) & keys) or bool(
        _gap_keys(context_gaps, CONFLICTING_CONTEXT)
    )


def _supported(evidence: SessionEvidence, contract: CoverageContract) -> bool:
    return contract.supported and not any(
        item.gap.reason in _UNSUPPORTED for item in evidence.acquisition_gaps
    )


def _settlement_stages(evidence: SessionEvidence) -> tuple[bool, bool]:
    """(execution terminal, deadline passed). A deadline without terminal is inert."""
    stages = {item.stage for item in evidence.run_settlement}
    terminal = RunSettlementStage.EXECUTION_TERMINAL in stages
    return terminal, terminal and RunSettlementStage.SETTLEMENT_DEADLINE in stages


def _seal(
    evidence: SessionEvidence, contract: CoverageContract, unsettled: _Unsettled
) -> tuple[bool, bool]:
    """Return (sealed, sealed-by-deadline-over-unsettled-nodes)."""
    terminal, deadline = _settlement_stages(evidence)
    settled = not (unsettled.process or unsettled.capture or evidence.acquisition_gaps)
    explicit = contract.sealed and (not unsettled.running or deadline)
    sealed = explicit or (terminal and (settled or deadline))
    return sealed, sealed and deadline and not settled


def _forced(unsettled: _Unsettled) -> tuple[str, ...]:
    return tuple(sorted(unsettled.process | unsettled.capture))


def settle_coverage(
    evidence: SessionEvidence,
    contract: CoverageContract | None,
    bindings: tuple[IdentityBinding, ...],
    process_gaps: tuple[InventoryGap, ...],
    context_gaps: tuple[InventoryGap, ...],
) -> Settlement:
    """Decide the seal from host facts. ``contract`` already carries child intents."""
    if contract is None:
        return Settlement(contract=None)
    expected = _descendants(evidence, {ref.key: ref for ref in contract.expected_nodes}, bindings)
    unsettled = _unsettled(evidence, expected, bindings, process_gaps)
    sealed, expired = _seal(evidence, contract, unsettled)
    return Settlement(
        contract=contract.model_copy(
            update={
                "expected_nodes": tuple(expected[key] for key in sorted(expected)),
                "sealed": sealed,
                "supported": _supported(evidence, contract),
            }
        ),
        gaps=_deadline_gaps(unsettled) if expired else (),
        unsettled_keys=_forced(unsettled) if expired else (),
        conflicting=_conflicting(set(expected), process_gaps, context_gaps),
    )
