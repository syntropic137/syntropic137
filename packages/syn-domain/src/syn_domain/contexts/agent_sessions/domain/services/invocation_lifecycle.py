"""Resolve process observations without treating process exit as capture settlement."""

from collections import defaultdict

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    InvocationLifecycleEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import InventoryGap

from .gap_reasons import GapReason


def lifecycle_gaps(
    observations: tuple[InvocationLifecycleEvidence, ...],
    bound: frozenset[str] = frozenset(),
) -> tuple[InventoryGap, ...]:
    """One gap per unsettled or abnormal invocation.

    ``bound`` holds the keys of invocations any producer ever claimed a native
    id for. A failure with no ``launched`` observation and no such claim is a
    transport failure before the wrapper announced (#1398); the host records
    ``launched`` whenever the announcement arrived (the launch is settled in a
    ``finally``), and a child journal refuses to finish an unlaunched child.
    """
    nodes: dict[str, list[InvocationLifecycleEvidence]] = defaultdict(list)
    for item in observations:
        nodes[item.node.key].append(item)
    gaps: list[InventoryGap] = []
    for key, items in sorted(nodes.items()):
        reason = _reason(items, bound=key in bound)
        if reason is not None:
            gaps.append(
                InventoryGap(
                    reason=reason,
                    node_keys=(key,),
                    evidence_ids=tuple(sorted({item.evidence.evidence_id for item in items})),
                )
            )
    return tuple(gaps)


def _outcome(items: list[InvocationLifecycleEvidence]) -> str | None:
    """The one status every producer's latest record agrees on, else None."""
    latest: dict[str, int] = {}
    for item in items:
        producer = item.evidence.producer_id
        latest[producer] = max(latest.get(producer, 0), item.sequence)
    outcomes = {item.status for item in items if item.sequence == latest[item.evidence.producer_id]}
    terminals = {item.status for item in items if item.status != "launched"}
    codes = {item.exit_code for item in items if item.exit_code is not None}
    if (
        len(outcomes) != 1
        or len(terminals) > 1
        or len(codes) > 1
        or (terminals and outcomes != terminals)
    ):
        return None
    return next(iter(outcomes))


def _reason(items: list[InvocationLifecycleEvidence], *, bound: bool) -> str | None:
    status = _outcome(items)
    if status is None:
        return GapReason.CONFLICTING_LIFECYCLE
    if status == "completed":
        return None
    if status == "launched":
        return GapReason.INVOCATION_RUNNING
    if status == "failed" and not bound and all(item.status != "launched" for item in items):
        return GapReason.INVOCATION_TRANSPORT_FAILED_BEFORE_ANNOUNCE
    return "invocation_" + status
