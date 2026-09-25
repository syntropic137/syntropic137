"""Host-side coverage seal: every known node settles before completeness (#1364).

Invariant: coverage is ``reconciled`` ONLY if every node the evidence names
for the run (registration, intent, child context, edge, platform session,
binding, capture or transcript) is accounted for, settled and non-conflicting.
Anything known but unaccounted blocks reconciliation: ``open`` before the
settlement deadline, ``missing`` or ``conflicting`` after it.

Rule (pure; recomputed on every reconstruction, never mutating a revision):

1. Expected nodes are the host contract's nodes plus every other node the run's
   evidence names, except aliases that another expected node already accounts
   for: a native transcript bound (registered or corroborated) to an expected
   owner, and a platform session named by the same host record as an expected
   invocation. Everything else must prove itself.
2. A node is SETTLED when its process is terminal (an invocation's latest
   lifecycle is completed, failed, cancelled or launch_failed) and its capture
   is terminal (the latest local receipt through its binding is not pending;
   a failed launch needs no body). Unresolved child attempt claims, unresolved
   parentage and a live acquisition failure (e.g. an unreadable child journal)
   are also unsettled: the host cannot yet say what the run contains.
3. The host seals once the execution is terminal AND everything is settled.
   A parent finishing is never enough on its own.
4. Bounded settlement: once the SETTLEMENT_DEADLINE fact exists (recorded a
   grace after the terminal event, see ``HostSessionEvidenceProjector``), the
   seal stops waiting. Unsettled processes, captures and child claims become
   explicit gaps and coverage is ``missing``; unresolved parentage becomes a gap
   and coverage is ``conflicting``. Timestamps bound waiting, never parentage.
5. Any conflicting lifecycle, child context, parentage, cycle, binding or
   source claim makes coverage ``conflicting`` regardless of the deadline.
6. A run with no host registration (no coverage contract) stays ``unknown``
   while it runs and becomes ``unsupported`` with a ``no_host_registration``
   gap once its execution is terminal: legacy and uninstrumented runs are
   classified, never reconciled.

An explicitly sealed producer contract seals without the terminal fact, but
never over a running invocation or unresolved claim before the deadline.
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

from .gap_reasons import CONFLICT_REASONS, GapReason

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
        CoverageContract,
        SessionEvidence,
    )
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
        CaptureReceipt,
        IdentityBinding,
        InventoryNode,
        InventoryNodeRef,
    )

_UNSUPPORTED = frozenset(UnsupportedEvidenceIssue)
_VERIFIED = (EvidenceClass.REGISTERED, EvidenceClass.CORROBORATED)


@dataclass(frozen=True)
class Settlement:
    contract: CoverageContract | None
    gaps: tuple[InventoryGap, ...] = ()
    unsettled_keys: tuple[str, ...] = ()
    conflicting: bool = False
    uninstrumented: bool = False


@dataclass(frozen=True)
class SettlementInput:
    """Everything the resolver already decided; settlement adds no new claims."""

    evidence: SessionEvidence
    contract: CoverageContract | None
    nodes: tuple[InventoryNode, ...]
    bindings: tuple[IdentityBinding, ...]
    gaps: tuple[InventoryGap, ...]


def capture_aliases(bindings: tuple[IdentityBinding, ...]) -> dict[str, str]:
    return {
        binding.owner.key: binding.transcript.key
        for binding in bindings
        if binding.confidence in _VERIFIED
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


def _platform_links(evidence: SessionEvidence) -> dict[str, set[str]]:
    """Platform session -> invocations named by the same host record."""
    by_record: dict[tuple[str, str], list[InventoryNodeRef]] = defaultdict(list)
    for claim in evidence.memberships:
        if claim.confidence is EvidenceClass.REGISTERED:
            by_record[(claim.evidence.producer_id, claim.evidence.evidence_id)].append(claim.node)
    links: dict[str, set[str]] = defaultdict(set)
    for refs in by_record.values():
        invocations = {ref.key for ref in refs if ref.kind == "invocation"}
        for ref in refs:
            if ref.kind == "platform":
                links[ref.key] |= invocations
    return links


def _expected(data: SettlementInput, contract: CoverageContract) -> dict[str, InventoryNodeRef]:
    known = {node.ref.key: node.ref for node in data.nodes}
    known.update((ref.key, ref) for ref in contract.expected_nodes)
    owners = {
        binding.transcript.key: binding.owner.key
        for binding in data.bindings
        if binding.confidence in _VERIFIED
    }
    links = _platform_links(data.evidence)
    expected: dict[str, InventoryNodeRef] = {}
    for key, ref in known.items():
        if ref.kind == "transcript" and owners.get(key) in known:
            continue  # Its owner accounts for it; capture resolves through the binding.
        if ref.kind == "platform" and links.get(key, set()) & known.keys():
            continue  # Represented by the invocation its own host record names.
        expected[key] = ref
    return expected


def _gap_keys(gaps: tuple[InventoryGap, ...], *reasons: GapReason) -> set[str]:
    return {key for gap in gaps if gap.reason in reasons for key in gap.node_keys}


@dataclass(frozen=True)
class _Unsettled:
    running: frozenset[str]
    process: frozenset[str]
    capture: frozenset[str]
    child_context: frozenset[str]
    parentage: frozenset[str]
    acquiring: bool

    @property
    def claims(self) -> bool:
        return bool(self.child_context or self.parentage)

    @property
    def settled(self) -> bool:
        return not (self.process or self.capture or self.claims or self.acquiring)


def _unsettled(data: SettlementInput, expected: dict[str, InventoryNodeRef]) -> _Unsettled:
    keys = set(expected)
    running = _gap_keys(data.gaps, GapReason.INVOCATION_RUNNING) & keys
    # A registered invocation with no outcome at all has not settled either.
    # Only the host seal waits on it; an explicit producer seal predates this.
    observed = {item.node.key for item in data.evidence.invocation_lifecycle}
    unobserved = {
        key for key, ref in expected.items() if ref.kind == "invocation" and key not in observed
    }
    launch_failed = _gap_keys(data.gaps, GapReason.INVOCATION_LAUNCH_FAILED)
    states = expected_capture_states(data.evidence, data.bindings, keys)
    capture = {
        key
        for key, values in states.items()
        if key not in launch_failed and (not values or BodyAvailability.PENDING in values)
    }
    return _Unsettled(
        running=frozenset(running),
        process=frozenset(running | unobserved),
        capture=frozenset(capture),
        child_context=frozenset(_gap_keys(data.gaps, GapReason.UNVERIFIED_CONTEXT)),
        parentage=frozenset(_gap_keys(data.gaps, GapReason.UNRESOLVED_PARENTAGE)),
        acquiring=bool(data.evidence.acquisition_gaps),
    )


def _deadline_gaps(unsettled: _Unsettled) -> tuple[InventoryGap, ...]:
    claims = (
        (GapReason.INVOCATION_UNSETTLED_AT_SEAL, unsettled.process),
        (GapReason.CAPTURE_UNSETTLED_AT_SEAL, unsettled.capture - unsettled.process),
        (GapReason.CHILD_CONTEXT_UNRESOLVED_AT_SEAL, unsettled.child_context),
        (GapReason.PARENTAGE_UNRESOLVED_AT_SEAL, unsettled.parentage),
    )
    return tuple(
        InventoryGap(reason=reason, node_keys=tuple(sorted(keys)))
        for reason, keys in claims
        if keys
    )


def _settlement_stages(evidence: SessionEvidence) -> tuple[bool, bool]:
    """(execution terminal, deadline passed). A deadline without terminal is inert."""
    stages = {item.stage for item in evidence.run_settlement}
    terminal = RunSettlementStage.EXECUTION_TERMINAL in stages
    return terminal, terminal and RunSettlementStage.SETTLEMENT_DEADLINE in stages


def _seal(
    evidence: SessionEvidence, contract: CoverageContract, unsettled: _Unsettled
) -> tuple[bool, bool]:
    """Return (sealed, sealed-by-deadline-over-unsettled-claims)."""
    terminal, deadline = _settlement_stages(evidence)
    blocked = bool(unsettled.running) or unsettled.claims
    explicit = contract.sealed and (not blocked or deadline)
    sealed = explicit or (terminal and (unsettled.settled or deadline))
    return sealed, sealed and deadline and not unsettled.settled


def _supported(evidence: SessionEvidence, contract: CoverageContract) -> bool:
    return contract.supported and not any(
        item.gap.reason in _UNSUPPORTED for item in evidence.acquisition_gaps
    )


def _uninstrumented(data: SettlementInput) -> Settlement:
    terminal, _ = _settlement_stages(data.evidence)
    if not terminal:
        return Settlement(contract=None)
    gap = InventoryGap(
        reason=GapReason.NO_HOST_REGISTRATION,
        node_keys=tuple(sorted(node.ref.key for node in data.nodes)),
    )
    return Settlement(contract=None, gaps=(gap,), uninstrumented=True)


def settle_coverage(data: SettlementInput) -> Settlement:
    """Decide the seal from host facts. ``data.contract`` already carries child intents."""
    contract = data.contract
    if contract is None:
        return _uninstrumented(data)
    expected = _expected(data, contract)
    unsettled = _unsettled(data, expected)
    sealed, expired = _seal(data.evidence, contract, unsettled)
    forced = unsettled.process | unsettled.capture | unsettled.child_context
    return Settlement(
        contract=contract.model_copy(
            update={
                "expected_nodes": tuple(expected[key] for key in sorted(expected)),
                "sealed": sealed,
                "supported": _supported(data.evidence, contract),
            }
        ),
        gaps=_deadline_gaps(unsettled) if expired else (),
        unsettled_keys=tuple(sorted(forced & expected.keys())) if expired else (),
        conflicting=any(gap.reason in CONFLICT_REASONS for gap in data.gaps)
        or (expired and bool(unsettled.parentage)),
    )
