"""Server-side inventory summary: counts, completeness and display text (#1398 D).

CLI, dashboard and agent plugins print these fields verbatim, so they cannot
disagree about what a run's inventory contains or whether it is complete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from syn_api.inventory_types import (
    ReconstructionStatus,
    SessionInventoryNamespace,
    SessionInventorySummary,
)
from syn_domain.contexts.agent_sessions import CoverageState

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import InventoryNamespaceCount, InventorySnapshot

_COVERAGE_DISPLAY: dict[CoverageState, str] = {
    CoverageState.RECONCILED: "reconciled: every expected session is accounted for",
    CoverageState.OPEN: "open: more sessions may still appear",
    CoverageState.UNKNOWN: "unknown: no completeness contract for this run",
    CoverageState.MISSING: "missing: expected sessions were not found",
    CoverageState.UNSUPPORTED: "unsupported: this harness cannot prove completeness",
    CoverageState.CONFLICTING: "conflicting: evidence disagrees about this run",
}


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _namespace(entry: InventoryNamespaceCount) -> SessionInventoryNamespace:
    name = entry.kind if entry.harness is None else f"{entry.kind}:{entry.harness}"
    return SessionInventoryNamespace(
        namespace=name, kind=entry.kind, harness=entry.harness, count=entry.count
    )


def _counts_display(
    snapshot: InventorySnapshot, namespaces: tuple[SessionInventoryNamespace, ...] | None
) -> str:
    counts = snapshot.counts
    gaps = _plural(counts.gap, "gap")
    if namespaces is None:
        return f"{_plural(counts.node, 'session')} (namespace split not recorded), {gaps}"
    platform = sum(entry.count for entry in namespaces if entry.kind == "platform")
    invocations = sum(entry.count for entry in namespaces if entry.kind == "invocation")
    native = [entry for entry in namespaces if entry.kind == "transcript"]
    native_total = sum(entry.count for entry in native)
    parts = [_plural(platform, "platform session")]
    transcripts = _plural(native_total, "native transcript")
    if native:
        per_harness = ", ".join(f"{entry.harness} {entry.count}" for entry in native)
        transcripts = f"{transcripts} ({per_harness})"
    parts.append(transcripts)
    parts.append(_plural(invocations, "invocation"))
    parts.append(gaps)
    return ", ".join(parts)


def build_summary(
    *,
    execution_id: str,
    snapshot: InventorySnapshot | None,
    status: ReconstructionStatus,
    later_evidence_pending: bool,
    remote_replication: Literal["enabled", "disabled"],
) -> SessionInventorySummary:
    follow_up = f"syn execution sessions {execution_id} --all"
    if snapshot is None:
        return SessionInventorySummary(
            complete=False,
            coverage_state="unknown",
            coverage_display="unknown: no inventory revision is published yet",
            revision=None,
            distinct_sessions=None,
            platform_sessions=None,
            invocations=None,
            native_transcripts=None,
            gaps=None,
            namespaces=None,
            counts_display=f"No published inventory (reconstruction {status.replace('_', ' ')})",
            remote_replication=remote_replication,
            follow_up_command=follow_up,
        )
    counts = snapshot.counts
    namespaces = (
        tuple(_namespace(entry) for entry in counts.namespaces)
        if counts.namespaces is not None
        else None
    )

    def total(kind: str) -> int | None:
        if namespaces is None:
            return None
        return sum(entry.count for entry in namespaces if entry.kind == kind)

    state = snapshot.coverage.state
    return SessionInventorySummary(
        complete=state is CoverageState.RECONCILED
        and status == "current"
        and not later_evidence_pending,
        coverage_state=state.value,
        coverage_display=_COVERAGE_DISPLAY[state],
        revision=snapshot.revision,
        distinct_sessions=counts.node,
        platform_sessions=total("platform"),
        invocations=total("invocation"),
        native_transcripts=total("transcript"),
        gaps=counts.gap,
        namespaces=namespaces,
        counts_display=_counts_display(snapshot, namespaces),
        remote_replication=remote_replication,
        follow_up_command=follow_up,
    )
