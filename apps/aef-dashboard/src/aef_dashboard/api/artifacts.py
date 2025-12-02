"""Artifact API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from aef_dashboard.models.schemas import ArtifactResponse, ArtifactSummary
from aef_dashboard.read_models import ArtifactReadModel, get_all_artifacts

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _artifact_to_summary(artifact: ArtifactReadModel) -> ArtifactSummary:
    """Convert an ArtifactReadModel to an ArtifactSummary."""
    return ArtifactSummary(
        id=artifact.id,
        workflow_id=artifact.workflow_id,
        phase_id=artifact.phase_id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        size_bytes=artifact.size_bytes,
        created_at=artifact.created_at,
    )


@router.get("", response_model=list[ArtifactSummary])
async def list_artifacts(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    phase_id: str | None = Query(None, description="Filter by phase ID (requires workflow_id)"),
    artifact_type: str | None = Query(None, description="Filter by artifact type"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[ArtifactSummary]:
    """List artifacts with optional filtering."""
    artifacts = await get_all_artifacts()

    # Filter by workflow_id if provided
    if workflow_id:
        artifacts = [a for a in artifacts if a.workflow_id == workflow_id]

    # Filter by phase_id if provided
    if phase_id:
        artifacts = [a for a in artifacts if a.phase_id == phase_id]

    # Filter by artifact_type if provided
    if artifact_type:
        artifacts = [a for a in artifacts if a.artifact_type == artifact_type]

    # Apply limit
    artifacts = artifacts[:limit]

    return [_artifact_to_summary(a) for a in artifacts]


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    include_content: bool = Query(  # noqa: ARG001 - API parameter for future use
        False, description="Include artifact content in response"
    ),
) -> ArtifactResponse:
    """Get artifact details by ID."""
    artifacts = await get_all_artifacts()
    artifact = next((a for a in artifacts if a.id == artifact_id), None)

    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    return ArtifactResponse(
        id=artifact.id,
        workflow_id=artifact.workflow_id,
        phase_id=artifact.phase_id,
        session_id=None,
        artifact_type=artifact.artifact_type,
        is_primary_deliverable=False,
        content=None,  # Content not stored in read model
        content_type="text/markdown",
        content_hash=None,
        size_bytes=artifact.size_bytes,
        title=artifact.title,
        derived_from=[],
        created_at=artifact.created_at,
        created_by=None,
        metadata={},
    )


@router.get("/{artifact_id}/content")
async def get_artifact_content(artifact_id: str) -> dict[str, str | None]:
    """Get artifact content only (for large artifacts)."""
    artifacts = await get_all_artifacts()
    artifact = next((a for a in artifacts if a.id == artifact_id), None)

    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    return {
        "artifact_id": artifact_id,
        "content": None,  # Content not stored in read model
        "content_type": "text/markdown",
    }
