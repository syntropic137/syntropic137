"""#2108: a trial's starting checkout and each phase's image reach the execution detail.

Both were only on the aggregate. An eval trial is judged against its base
from the read model at query time, so the read model must hold the checkout
the way the aggregate does: the FIRST provisioning's, never overwritten by a
later phase. The image manifest is per phase and the latest provisioning's,
because a retried phase runs on a fresh workspace.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.ImageManifestValueObjects import (
    ImageManifestContent,
    ImageManifestReading,
    ImageManifestState,
)
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

if TYPE_CHECKING:
    from syn_domain.pagination import ProjectionRecord

pytestmark = pytest.mark.unit


def _copying_store() -> InMemoryProjectionStore:
    """A store that hands out a copy, as Postgres does: an edit never saved is lost.

    The in-memory store returns its live document, so a handler that forgot
    to save would still look right through it.
    """
    store = InMemoryProjectionStore()
    live = store.get

    async def get(projection: str, key: str) -> ProjectionRecord | None:
        return copy.deepcopy(await live(projection, key))

    store.get = get  # pyright: ignore[reportAttributeAccessIssue]  # instance-level double
    return store


REPO = "syntropic137/syntropic137"
FIRST, LATER = "a" * 40, "b" * 40


def _manifest(build_commit: str) -> ImageManifestReading:
    return ImageManifestReading(
        state=ImageManifestState.READ,
        manifest=ImageManifestContent(
            provider="claude",
            provider_version="2.1.0",
            components={"node": "22"},
            build_commit=build_commit,
            built_at="2026-10-27T00:00:00Z",
            manifest_digest="d" * 64,
        ),
    )


def _provisioned(
    phase_id: str, sha: str | None, manifest: ImageManifestReading | None
) -> WorkspaceProvisionedForPhaseEvent:
    return WorkspaceProvisionedForPhaseEvent(
        workflow_id="wf",
        execution_id="exec-1",
        phase_id=phase_id,
        workspace_id=f"ws-{phase_id}",
        session_id=f"s-{phase_id}",
        provisioned_at=datetime(2026, 10, 27, tzinfo=UTC),
        checked_out_commits=None if sha is None else [SourceCommit(repository=REPO, sha=sha)],
        image_manifest=manifest,
    )


async def _projection(*phase_ids: str) -> WorkflowExecutionDetailProjection:
    projection = WorkflowExecutionDetailProjection(_copying_store())
    await projection.on_workflow_execution_started(
        {"execution_id": "exec-1", "workflow_id": "wf", "workflow_name": "wf"}
    )
    for phase_id in phase_ids:
        await projection.on_phase_started(
            {"execution_id": "exec-1", "phase_id": phase_id, "phase_name": phase_id}
        )
    return projection


async def _detail(projection: WorkflowExecutionDetailProjection) -> WorkflowExecutionDetail:
    row = await projection._store.get(projection.PROJECTION_NAME, "exec-1")
    return WorkflowExecutionDetail.from_dict(row)


async def test_the_first_provisioning_is_the_starting_checkout_and_a_later_one_is_not() -> None:
    projection = await _projection("p1", "p2")
    await projection.on_workspace_provisioned_for_phase(_provisioned("p1", FIRST, None))
    await projection.on_workspace_provisioned_for_phase(_provisioned("p2", LATER, None))

    detail = await _detail(projection)

    assert detail.starting_checkout == (SourceCommit(repository=REPO, sha=FIRST),)


async def test_a_first_provisioning_with_no_checkout_stays_absent() -> None:
    """As the aggregate: the first provisioning decides, even when it recorded none."""
    projection = await _projection("p1", "p2")
    await projection.on_workspace_provisioned_for_phase(_provisioned("p1", None, None))
    await projection.on_workspace_provisioned_for_phase(_provisioned("p2", LATER, None))

    assert (await _detail(projection)).starting_checkout == ()


async def test_the_checkout_is_kept_when_the_phase_row_is_not_projected_yet() -> None:
    projection = await _projection()
    await projection.on_workspace_provisioned_for_phase(_provisioned("p1", FIRST, None))

    assert (await _detail(projection)).starting_checkout == (
        SourceCommit(repository=REPO, sha=FIRST),
    )


async def test_each_phase_carries_its_latest_image_manifest() -> None:
    projection = await _projection("p1", "p2")
    await projection.on_workspace_provisioned_for_phase(_provisioned("p1", FIRST, _manifest("c1")))
    # A retried p1 runs on a fresh workspace: its image is the phase's now.
    await projection.on_workspace_provisioned_for_phase(_provisioned("p1", FIRST, _manifest("c2")))
    await projection.on_workspace_provisioned_for_phase(
        _provisioned("p2", FIRST, ImageManifestReading.absent())
    )

    phases = {p.workflow_phase_id: p.image_manifest for p in (await _detail(projection)).phases}

    assert phases == {"p1": _manifest("c2"), "p2": ImageManifestReading.absent()}


def test_the_read_model_round_trips_both_fields() -> None:
    detail = WorkflowExecutionDetail.from_dict(
        {
            "workflow_execution_id": "exec-1",
            "workflow_id": "wf",
            "starting_checkout": [{"repository": REPO, "sha": FIRST}],
            "phases": [{"workflow_phase_id": "p1", "image_manifest": _manifest("c1").model_dump()}],
        }
    )

    again = WorkflowExecutionDetail.from_dict(detail.to_dict())

    assert again.starting_checkout == detail.starting_checkout
    assert again.phases[0].image_manifest == _manifest("c1")
