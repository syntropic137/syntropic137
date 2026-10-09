"""GET /workflows/{id}/latest-outputs: each phase's last output in one request.

The workflow detail page shows every phase's latest output. Without this the
client asked the artifact list once per phase and picked a row itself, which is
N requests and a rule ("newest primary deliverable") every client had to
re-derive. These pin the envelope: every phase present in phase order, a phase
with no output yet reported as null rather than dropped, and the artifact
fields carried through the same mapping the artifact list uses.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_api.routes.workflows.queries import get_workflow_latest_outputs_endpoint
from syn_api.types import (
    ArtifactError,
    ArtifactSummary,
    Err,
    Ok,
    PhaseDefinitionResponse,
    WorkflowDetail,
    WorkflowError,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)

pytestmark = pytest.mark.unit


def _phase(phase_id: str, order: int) -> PhaseDefinitionResponse:
    return PhaseDefinitionResponse(phase_id=phase_id, name=phase_id.title(), order=order)


def _detail(*phases: PhaseDefinitionResponse) -> WorkflowDetail:
    return WorkflowDetail(
        id="wf-1",
        name="wf",
        workflow_type="custom",
        classification="simple",
        phases=list(phases),
    )


async def _call(
    detail_result: Ok[WorkflowDetail] | Err[WorkflowError],
    outputs: Ok[dict[str, ArtifactSummary | None]] | Err[ArtifactError],
):
    with (
        patch("syn_api.routes.workflows.queries.get_projection_mgr", return_value=MagicMock()),
        patch("syn_api.prefix_resolver.resolve_or_raise", new=AsyncMock(return_value="wf-1")),
        patch(
            "syn_api.routes.workflows.queries.get_workflow",
            new=AsyncMock(return_value=detail_result),
        ),
        patch(
            "syn_api.routes.artifacts.latest_phase_outputs",
            new=AsyncMock(return_value=outputs),
        ) as latest,
    ):
        return await get_workflow_latest_outputs_endpoint("wf-1"), latest


async def test_every_phase_in_order_with_null_for_no_output() -> None:
    artifact = ArtifactSummary(
        id="art-1",
        workflow_id="wf-1",
        execution_id="ex-2",
        phase_id="plan",
        artifact_type="document",
        title="Plan",
        size_bytes=12,
        created_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    resp, latest = await _call(
        Ok(_detail(_phase("review", 2), _phase("plan", 1))),
        Ok({"plan": artifact, "review": None}),
    )

    latest.assert_awaited_once_with("wf-1", ["plan", "review"])
    assert [(p.phase_id, p.phase_name) for p in resp.phases] == [
        ("plan", "Plan"),
        ("review", "Review"),
    ]
    assert resp.phases[0].artifact is not None
    assert resp.phases[0].artifact.id == "art-1"
    assert resp.phases[0].artifact.execution_id == "ex-2"
    assert resp.phases[1].artifact is None


async def test_unknown_workflow_is_404() -> None:
    with pytest.raises(HTTPException) as exc:
        await _call(Err(WorkflowError.NOT_FOUND, message="nope"), Ok({}))
    assert exc.value.status_code == 404


async def test_a_storage_failure_is_500_not_empty() -> None:
    """An outage must not read as "no phase has produced anything"."""
    with pytest.raises(HTTPException) as exc:
        await _call(Ok(_detail(_phase("plan", 1))), Err(ArtifactError.STORAGE_ERROR, message="x"))
    assert exc.value.status_code == 500


async def test_the_service_answers_every_phase_from_the_projection() -> None:
    from syn_api.routes.artifacts import latest_phase_outputs

    projection = ArtifactListProjection(InMemoryProjectionStore())
    await projection.on_artifact_created(
        {
            "artifact_id": "art-1",
            "workflow_id": "wf-1",
            "execution_id": "ex-1",
            "phase_id": "plan",
            "artifact_type": "document",
            "title": "Plan",
            "content": "hello",
            "created_at": "2026-10-02T10:00:00+00:00",
            "agent_provider": "claude",
            "is_primary_deliverable": True,
        }
    )
    mgr = MagicMock()
    mgr.artifact_list = projection
    with (
        patch("syn_api.routes.artifacts.ensure_connected", new=AsyncMock()),
        patch("syn_api.routes.artifacts.get_projection_mgr", return_value=mgr),
    ):
        result = await latest_phase_outputs("wf-1", ["plan", "review"])

    assert isinstance(result, Ok)
    plan = result.value["plan"]
    assert plan is not None
    assert (plan.id, plan.title, plan.size_bytes, plan.agent_provider) == (
        "art-1",
        "Plan",
        5,
        "claude",
    )
    assert result.value["review"] is None


class _CountingStore(InMemoryProjectionStore):
    """Records every read the service makes of the store."""

    def __post_init__(self) -> None:
        super().__post_init__()
        self.reads: list[str] = []

    async def query(self, *args, **kwargs):
        self.reads.append("query")
        return await super().query(*args, **kwargs)

    async def newest_per_group(self, *args, **kwargs):
        self.reads.append("newest_per_group")
        return await super().newest_per_group(*args, **kwargs)


async def _write(
    projection: ArtifactListProjection, artifact_id: str, phase: str, at: str, *, primary: bool
) -> None:
    await projection.on_artifact_created(
        {
            "artifact_id": artifact_id,
            "workflow_id": "wf-1",
            "phase_id": phase,
            "artifact_type": "document",
            "title": artifact_id,
            "content": "x",
            "created_at": at,
            "is_primary_deliverable": primary,
        }
    )


async def test_the_service_reads_the_store_once_per_workflow_not_per_phase() -> None:
    """N phases used to cost N or more windowed reads, bodies included."""
    from syn_api.routes.artifacts import latest_phase_outputs

    store = _CountingStore()
    projection = ArtifactListProjection(store)
    phases = [f"phase-{i}" for i in range(6)]
    for phase in phases:
        for i in range(12):
            await _write(
                projection,
                f"{phase}-support-{i:02d}",
                phase,
                f"2026-10-02T10:{i:02d}:00Z",
                primary=False,
            )
        await _write(
            projection, f"{phase}-deliverable", phase, "2026-10-02T09:00:00Z", primary=True
        )
    mgr = MagicMock()
    mgr.artifact_list = projection
    with (
        patch("syn_api.routes.artifacts.ensure_connected", new=AsyncMock()),
        patch("syn_api.routes.artifacts.get_projection_mgr", return_value=mgr),
    ):
        result = await latest_phase_outputs("wf-1", phases)

    assert isinstance(result, Ok)
    assert {p: (a.id if a else None) for p, a in result.value.items()} == {
        p: f"{p}-deliverable" for p in phases
    }
    assert store.reads == ["newest_per_group"]
