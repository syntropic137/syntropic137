"""#1004 slice 1: the commits a run recorded reach the execution detail.

The start event records the commit each repository was at, and each phase's
provisioning records what its workspace checked out. Both were dropped by the
projection. A run that predates the fields recorded nothing, so the read model
must say "not recorded" (None), never an empty list that claims no repository.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
    WorkspaceProvisionedForPhaseEvent,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
    WorkflowExecutionDetail,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit

REPO, OTHER = "acme/api", "acme/web"
START, FIRST, RETRY = "a" * 40, "b" * 40, "c" * 40


def _provisioned(
    phase_id: str, commits: list[SourceCommit] | None
) -> WorkspaceProvisionedForPhaseEvent:
    return WorkspaceProvisionedForPhaseEvent(
        workflow_id="wf",
        execution_id="exec-1",
        phase_id=phase_id,
        workspace_id=f"ws-{phase_id}",
        session_id=f"s-{phase_id}",
        provisioned_at=datetime(2026, 11, 26, tzinfo=UTC),
        checked_out_commits=commits,
    )


async def _started(
    source_commits: list[dict[str, str | None]] | None,
) -> WorkflowExecutionDetailProjection:
    projection = WorkflowExecutionDetailProjection(InMemoryProjectionStore())
    ids = {"execution_id": "exec-1", "workflow_id": "wf", "workflow_name": "wf"}
    # An older start event has no `source_commits` key at all.
    await projection.on_workflow_execution_started(
        ids if source_commits is None else {**ids, "source_commits": source_commits}
    )
    await projection.on_phase_started(
        {"execution_id": "exec-1", "phase_id": "p1", "phase_name": "p1"}
    )
    return projection


async def _detail(projection: WorkflowExecutionDetailProjection) -> WorkflowExecutionDetail:
    row = await projection._store.get(projection.PROJECTION_NAME, "exec-1")
    # Round-tripped as the store would: what the API reads is from_dict(to_dict()).
    return WorkflowExecutionDetail.from_dict(WorkflowExecutionDetail.from_dict(row).to_dict())


async def test_the_start_and_each_phase_carry_the_commits_they_recorded() -> None:
    projection = await _started(
        [{"repository": REPO, "sha": START}, {"repository": OTHER, "sha": None}]
    )
    await projection.on_workspace_provisioned_for_phase(
        _provisioned("p1", [SourceCommit(repository=REPO, sha=FIRST)])
    )

    detail = await _detail(projection)

    # "Recorded, not resolved" (sha None) stays distinct from "not recorded".
    assert detail.source_commits == (
        SourceCommit(repository=REPO, sha=START),
        SourceCommit(repository=OTHER, sha=None),
    )
    assert detail.phases[0].checked_out_commits == (SourceCommit(repository=REPO, sha=FIRST),)


async def test_a_retried_phase_carries_its_latest_checkout() -> None:
    projection = await _started(None)
    await projection.on_workspace_provisioned_for_phase(
        _provisioned("p1", [SourceCommit(repository=REPO, sha=FIRST)])
    )
    await projection.on_workspace_provisioned_for_phase(
        _provisioned("p1", [SourceCommit(repository=REPO, sha=RETRY)])
    )

    detail = await _detail(projection)

    assert detail.phases[0].checked_out_commits == (SourceCommit(repository=REPO, sha=RETRY),)
    # The run's starting checkout is still the first provisioning's (#2108).
    assert detail.starting_checkout == (SourceCommit(repository=REPO, sha=FIRST),)


async def test_a_run_that_recorded_no_commits_reads_not_recorded_not_empty() -> None:
    projection = await _started(None)
    await projection.on_workspace_provisioned_for_phase(_provisioned("p1", None))

    detail = await _detail(projection)

    assert detail.source_commits is None
    assert detail.phases[0].checked_out_commits is None


async def test_a_row_stored_before_the_fields_reads_not_recorded() -> None:
    """A row projected at v20 has neither key until the rebuild reaches it."""
    projection = await _started([{"repository": REPO, "sha": START}])
    await projection.on_workspace_provisioned_for_phase(
        _provisioned("p1", [SourceCommit(repository=REPO, sha=FIRST)])
    )
    row = await projection._store.get(projection.PROJECTION_NAME, "exec-1")
    del row["source_commits"]
    del row["phases"][0]["checked_out_commits"]

    detail = WorkflowExecutionDetail.from_dict(row)

    assert detail.source_commits is None
    assert detail.phases[0].checked_out_commits is None
