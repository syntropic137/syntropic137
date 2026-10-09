"""GET /workflows/{id}/latest-outputs: every phase's latest output in one request.

Its own module so the workflow query routes stay inside the file-size gate;
mounted on the same ``/workflows`` router by the package.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from syn_api._wiring import get_projection_mgr
from syn_api.routes.artifacts import ArtifactSummaryResponse  # noqa: TC001 - pydantic field type
from syn_api.routes.workflows.queries import get_workflow
from syn_api.types import Err

router = APIRouter(prefix="/workflows", tags=["workflows"])


class PhaseLatestOutputResponse(BaseModel):
    """One phase of a workflow and the output it last produced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: str
    phase_name: str
    artifact: ArtifactSummaryResponse | None = None
    """The phase's newest primary deliverable across every run of the
    workflow; null when no run of this phase has produced one yet."""


class WorkflowLatestOutputsResponse(BaseModel):
    """Every phase of a workflow, in phase order, with its latest output.

    One request for the whole workflow detail page instead of one artifact
    query per phase."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: str
    phases: list[PhaseLatestOutputResponse]


@router.get("/{workflow_id}/latest-outputs", response_model=WorkflowLatestOutputsResponse)
async def get_workflow_latest_outputs_endpoint(workflow_id: str) -> WorkflowLatestOutputsResponse:
    """Each phase's latest output: its newest primary deliverable across all runs."""
    from syn_api.prefix_resolver import resolve_or_raise
    from syn_api.routes.artifacts import latest_phase_outputs, to_artifact_summary_response

    mgr = get_projection_mgr()
    workflow_id = await resolve_or_raise(mgr.store, "workflow_details", workflow_id, "Workflow")
    wf_result = await get_workflow(workflow_id)
    if isinstance(wf_result, Err):
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    phases = sorted(wf_result.value.phases, key=lambda p: p.order)
    outputs = await latest_phase_outputs(workflow_id, [p.phase_id for p in phases])
    if isinstance(outputs, Err):
        raise HTTPException(status_code=500, detail=outputs.message)

    return WorkflowLatestOutputsResponse(
        workflow_id=workflow_id,
        phases=[
            PhaseLatestOutputResponse(
                phase_id=p.phase_id,
                phase_name=p.name,
                artifact=(
                    to_artifact_summary_response(artifact)
                    if (artifact := outputs.value.get(p.phase_id)) is not None
                    else None
                ),
            )
            for p in phases
        ],
    )
