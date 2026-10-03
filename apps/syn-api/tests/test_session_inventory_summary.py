"""Server-side inventory summary: one completeness verdict and display text for every client."""

from uuid import uuid4

import pytest

from syn_api.routes.executions.inventory_summary import build_summary
from syn_domain.contexts.agent_sessions import (
    CoverageState,
    InventoryCounts,
    InventoryCoverage,
    InventoryNamespaceCount,
    InventorySnapshot,
    RunIdentity,
)

pytestmark = pytest.mark.unit

RUN = RunIdentity(source_instance_id="installation", execution_id="run-1")


def _snapshot(
    state: CoverageState, namespaces: tuple[InventoryNamespaceCount, ...] | None
) -> InventorySnapshot:
    return InventorySnapshot(
        snapshot_id=uuid4(),
        run=RUN,
        revision="rev",
        resolver_version="test/1",
        evidence_watermark=1,
        coverage=InventoryCoverage(state=state),
        counts=InventoryCounts(
            node=3, membership=0, edge=0, capture=0, gap=1, namespaces=namespaces
        ),
    )


NAMESPACES = (
    InventoryNamespaceCount(kind="platform", count=1),
    InventoryNamespaceCount(kind="transcript", harness="claude", count=2),
)


def test_complete_requires_reconciled_current_and_no_later_evidence() -> None:
    snapshot = _snapshot(CoverageState.RECONCILED, NAMESPACES)
    common = {"execution_id": "run-1", "snapshot": snapshot, "remote_replication": "enabled"}
    assert build_summary(**common, status="current", later_evidence_pending=False).complete
    assert not build_summary(**common, status="pending", later_evidence_pending=True).complete
    assert not build_summary(**common, status="failed", later_evidence_pending=False).complete


@pytest.mark.parametrize(
    "state",
    [s for s in CoverageState if s is not CoverageState.RECONCILED],
)
def test_every_other_coverage_state_is_incomplete(state: CoverageState) -> None:
    summary = build_summary(
        execution_id="run-1",
        snapshot=_snapshot(state, NAMESPACES),
        status="current",
        later_evidence_pending=False,
        remote_replication="disabled",
    )
    assert not summary.complete
    assert summary.coverage_state == state.value
    assert summary.coverage_display.startswith(state.value)


def test_platform_and_native_counts_are_separate() -> None:
    summary = build_summary(
        execution_id="run-1",
        snapshot=_snapshot(CoverageState.OPEN, NAMESPACES),
        status="current",
        later_evidence_pending=False,
        remote_replication="disabled",
    )
    assert (summary.platform_sessions, summary.native_transcripts, summary.invocations) == (1, 2, 0)
    assert [entry.namespace for entry in summary.namespaces or ()] == [
        "platform",
        "transcript:claude",
    ]
    assert summary.counts_display == (
        "1 platform session, 2 native transcripts (claude 2), 0 invocations, 1 gap"
    )
    assert summary.remote_replication == "disabled"
    assert summary.follow_up_command == "syn execution sessions run-1 --all"


def test_legacy_revision_without_namespace_split_does_not_invent_zeroes() -> None:
    summary = build_summary(
        execution_id="run-1",
        snapshot=_snapshot(CoverageState.OPEN, None),
        status="current",
        later_evidence_pending=False,
        remote_replication="enabled",
    )
    assert summary.platform_sessions is None
    assert summary.native_transcripts is None
    assert summary.namespaces is None
    assert summary.distinct_sessions == 3
    assert "namespace split not recorded" in summary.counts_display


def test_no_published_revision() -> None:
    summary = build_summary(
        execution_id="run-1",
        snapshot=None,
        status="not_started",
        later_evidence_pending=False,
        remote_replication="enabled",
    )
    assert not summary.complete
    assert summary.distinct_sessions is None
    assert summary.counts_display == "No published inventory (reconstruction not started)"
