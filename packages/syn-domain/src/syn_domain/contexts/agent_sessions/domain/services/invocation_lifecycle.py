"""Resolve process observations without treating process exit as capture settlement."""

from collections import defaultdict

from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    InvocationLifecycleEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import InventoryGap

INVOCATION_RUNNING = "invocation_running"
CONFLICTING_LIFECYCLE = "conflicting_invocation_lifecycle"
INVOCATION_LAUNCH_FAILED = "invocation_launch_failed"


def lifecycle_gaps(
    observations: tuple[InvocationLifecycleEvidence, ...],
) -> tuple[InventoryGap, ...]:
    nodes: dict[str, list[InvocationLifecycleEvidence]] = defaultdict(list)
    for item in observations:
        nodes[item.node.key].append(item)
    gaps: list[InventoryGap] = []
    for key, items in sorted(nodes.items()):
        reason = _reason(items)
        if reason is not None:
            gaps.append(
                InventoryGap(
                    reason=reason,
                    node_keys=(key,),
                    evidence_ids=tuple(sorted({item.evidence.evidence_id for item in items})),
                )
            )
    return tuple(gaps)


def _reason(items: list[InvocationLifecycleEvidence]) -> str | None:
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
        return CONFLICTING_LIFECYCLE
    status = next(iter(outcomes))
    if status == "completed":
        return None
    if status == "launched":
        return INVOCATION_RUNNING
    return "invocation_" + status
