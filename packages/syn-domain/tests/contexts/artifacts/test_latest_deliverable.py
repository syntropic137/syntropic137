"""A workflow phase's latest output: its newest primary deliverable.

The workflow detail page shows, per phase, what that phase last produced. The
only way to ask before was the artifact list filtered by workflow and phase,
once per phase, and then picking the right row on the client. These pin the
three ways picking it goes wrong: a newer supporting file standing in for the
deliverable, an undated row ranked as newest, and an answer hidden past the
first window of rows.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)

pytestmark = pytest.mark.unit

WORKFLOW = "wf-1"


async def _create(
    projection: ArtifactListProjection,
    artifact_id: str,
    *,
    created_at: str | None,
    phase_id: str = "plan",
    workflow_id: str = WORKFLOW,
    execution_id: str = "ex-1",
    primary: bool = True,
) -> None:
    await projection.on_artifact_created(
        {
            "artifact_id": artifact_id,
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "phase_id": phase_id,
            "artifact_type": "document",
            "title": artifact_id,
            "content": "x",
            "created_at": created_at,
            "is_primary_deliverable": primary,
        }
    )


@pytest.fixture
def projection() -> ArtifactListProjection:
    return ArtifactListProjection(InMemoryProjectionStore())


async def test_the_newest_run_wins(projection: ArtifactListProjection) -> None:
    await _create(projection, "old", created_at="2026-10-01T10:00:00+00:00", execution_id="ex-1")
    await _create(projection, "new", created_at="2026-10-02T10:00:00+00:00", execution_id="ex-2")

    latest = await projection.latest_deliverable(WORKFLOW, "plan")

    assert latest is not None
    assert latest.id == "new"


async def test_a_newer_supporting_file_is_not_the_output(
    projection: ArtifactListProjection,
) -> None:
    await _create(projection, "deliverable", created_at="2026-10-02T10:00:00+00:00")
    await _create(projection, "notes", created_at="2026-10-02T10:05:00+00:00", primary=False)

    latest = await projection.latest_deliverable(WORKFLOW, "plan")

    assert latest is not None
    assert latest.id == "deliverable"


async def test_only_this_workflow_and_phase(projection: ArtifactListProjection) -> None:
    await _create(projection, "mine", created_at="2026-10-01T10:00:00+00:00")
    await _create(
        projection, "other-phase", created_at="2026-10-03T10:00:00+00:00", phase_id="review"
    )
    await _create(
        projection, "other-workflow", created_at="2026-10-03T10:00:00+00:00", workflow_id="wf-2"
    )

    latest = await projection.latest_deliverable(WORKFLOW, "plan")

    assert latest is not None
    assert latest.id == "mine"


async def test_an_undated_row_is_never_latest(projection: ArtifactListProjection) -> None:
    """Nothing says an undated row is newer than anything (#920)."""
    await _create(projection, "undated", created_at=None)
    await _create(projection, "dated", created_at="2026-10-01T10:00:00+00:00")

    latest = await projection.latest_deliverable(WORKFLOW, "plan")

    assert latest is not None
    assert latest.id == "dated"


async def test_no_output_yet_is_none(projection: ArtifactListProjection) -> None:
    await _create(projection, "notes", created_at="2026-10-01T10:00:00+00:00", primary=False)

    assert await projection.latest_deliverable(WORKFLOW, "plan") is None
    assert await projection.latest_deliverable(WORKFLOW, "never-ran") is None


async def test_the_answer_past_the_first_window_is_found(
    projection: ArtifactListProjection,
) -> None:
    """A run that wrote many supporting files must not hide its deliverable."""
    await _create(projection, "deliverable", created_at="2026-10-01T09:00:00+00:00")
    for i in range(25):
        await _create(
            projection,
            f"support-{i:02d}",
            created_at=f"2026-10-01T10:{i:02d}:00+00:00",
            primary=False,
        )

    latest = await projection.latest_deliverable(WORKFLOW, "plan")

    assert latest is not None
    assert latest.id == "deliverable"
