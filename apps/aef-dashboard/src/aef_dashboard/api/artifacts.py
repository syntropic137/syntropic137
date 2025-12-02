"""Artifact API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from aef_adapters.storage import get_artifact_repository
from aef_dashboard.models.schemas import ArtifactResponse, ArtifactSummary

if TYPE_CHECKING:
    from aef_domain.contexts.artifacts._shared.ArtifactAggregate import ArtifactAggregate

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _artifact_to_summary(artifact: ArtifactAggregate) -> ArtifactSummary:
    """Convert an ArtifactAggregate to an ArtifactSummary."""
    return ArtifactSummary(
        id=str(artifact.id) if artifact.id else "",
        workflow_id=artifact.workflow_id,
        phase_id=artifact.phase_id,
        artifact_type=artifact.artifact_type.value if artifact.artifact_type else "other",
        title=artifact.title,
        size_bytes=artifact.size_bytes,
        created_at=None,  # Not tracked in aggregate state
    )


def _artifact_to_response(
    artifact: ArtifactAggregate, include_content: bool = False
) -> ArtifactResponse:
    """Convert an ArtifactAggregate to an ArtifactResponse."""
    return ArtifactResponse(
        id=str(artifact.id) if artifact.id else "",
        workflow_id=artifact.workflow_id,
        phase_id=artifact.phase_id,
        session_id=artifact.session_id,
        artifact_type=artifact.artifact_type.value if artifact.artifact_type else "other",
        is_primary_deliverable=artifact.is_primary_deliverable,
        content=artifact.content if include_content else None,
        content_type=artifact.content_type.value if artifact.content_type else "text/markdown",
        content_hash=artifact.content_hash,
        size_bytes=artifact.size_bytes,
        title=artifact.title,
        derived_from=artifact.derived_from or [],
        created_at=None,  # Not tracked in aggregate state
        created_by=None,  # Not tracked in aggregate state
        metadata={},  # Not exposed via property
    )


@router.get("", response_model=list[ArtifactSummary])
async def list_artifacts(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    phase_id: str | None = Query(None, description="Filter by phase ID (requires workflow_id)"),
    artifact_type: str | None = Query(None, description="Filter by artifact type"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[ArtifactSummary]:
    """List artifacts with optional filtering."""
    repo = get_artifact_repository()

    if workflow_id and phase_id:
        artifacts = repo.get_by_phase(workflow_id, phase_id)
    elif workflow_id:
        artifacts = repo.get_by_workflow(workflow_id)
    else:
        artifacts = repo.get_all()

    # Filter by artifact_type if provided
    if artifact_type:
        artifacts = [
            a for a in artifacts if a.artifact_type and a.artifact_type.value == artifact_type
        ]

    # Apply limit
    artifacts = artifacts[:limit]

    return [_artifact_to_summary(a) for a in artifacts]


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    include_content: bool = Query(False, description="Include artifact content in response"),
) -> ArtifactResponse:
    """Get artifact details by ID."""
    repo = get_artifact_repository()
    artifact = await repo.get(artifact_id)

    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    return _artifact_to_response(artifact, include_content=include_content)


@router.get("/{artifact_id}/content")
async def get_artifact_content(artifact_id: str) -> dict[str, str | None]:
    """Get artifact content only (for large artifacts)."""
    repo = get_artifact_repository()
    artifact = await repo.get(artifact_id)

    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    return {
        "artifact_id": artifact_id,
        "content": artifact.content,
        "content_type": artifact.content_type.value if artifact.content_type else "text/markdown",
    }
