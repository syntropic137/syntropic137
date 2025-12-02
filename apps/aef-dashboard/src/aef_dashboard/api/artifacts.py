"""Artifact API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

from aef_adapters.projections import get_projection_manager
from aef_dashboard.models.schemas import ArtifactResponse, ArtifactSummary
from aef_domain.contexts.artifacts.domain.queries import ListArtifactsQuery
from aef_domain.contexts.artifacts.slices.list_artifacts import ListArtifactsHandler

if TYPE_CHECKING:
    from aef_domain.contexts.artifacts.domain.read_models import (
        ArtifactSummary as DomainArtifactSummary,
    )

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _domain_artifact_to_api(artifact: DomainArtifactSummary) -> ArtifactSummary:
    """Convert domain ArtifactSummary to API ArtifactSummary."""
    return ArtifactSummary(
        id=artifact.id,
        workflow_id=artifact.workflow_id,
        phase_id=artifact.phase_id,
        artifact_type=artifact.artifact_type,
        title=artifact.name,
        size_bytes=0,  # Not tracked in current domain model
        created_at=artifact.created_at,
    )


@router.get("", response_model=list[ArtifactSummary])
async def list_artifacts(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    phase_id: str | None = Query(None, description="Filter by phase ID"),
    artifact_type: str | None = Query(None, description="Filter by artifact type"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[ArtifactSummary]:
    """List artifacts with optional filtering."""
    # Get projection manager and create handler
    manager = get_projection_manager()
    handler = ListArtifactsHandler(manager.artifact_list)

    # Build and execute query
    query = ListArtifactsQuery(
        workflow_id=workflow_id,
        phase_id=phase_id,
        artifact_type_filter=artifact_type,
        limit=limit,
    )
    artifacts = await handler.handle(query)

    return [_domain_artifact_to_api(a) for a in artifacts]


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    include_content: bool = Query(  # noqa: ARG001 - API parameter for future use
        False, description="Include artifact content in response"
    ),
) -> ArtifactResponse:
    """Get artifact details by ID."""
    # Get projection manager and create handler
    manager = get_projection_manager()
    handler = ListArtifactsHandler(manager.artifact_list)

    # Query all artifacts and find the matching one
    # TODO: Add a GetArtifactDetailQuery for direct lookup
    query = ListArtifactsQuery(limit=10000)
    artifacts = await handler.handle(query)
    artifact = next((a for a in artifacts if a.id == artifact_id), None)

    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    return ArtifactResponse(
        id=artifact.id,
        workflow_id=artifact.workflow_id,
        phase_id=artifact.phase_id,
        session_id=artifact.session_id,
        artifact_type=artifact.artifact_type,
        is_primary_deliverable=False,
        content=None,  # Content not stored in read model
        content_type="text/markdown",
        content_hash=None,
        size_bytes=0,
        title=artifact.name,
        derived_from=[],
        created_at=artifact.created_at,
        created_by=None,
        metadata={},
    )


@router.get("/{artifact_id}/content")
async def get_artifact_content(artifact_id: str) -> dict[str, str | None]:
    """Get artifact content only (for large artifacts)."""
    # Get projection manager and create handler
    manager = get_projection_manager()
    handler = ListArtifactsHandler(manager.artifact_list)

    # Query all artifacts and find the matching one
    query = ListArtifactsQuery(limit=10000)
    artifacts = await handler.handle(query)
    artifact = next((a for a in artifacts if a.id == artifact_id), None)

    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    return {
        "artifact_id": artifact_id,
        "content": None,  # Content not stored in read model
        "content_type": "text/markdown",
    }
