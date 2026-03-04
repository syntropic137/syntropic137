"""Artifact API endpoints — thin wrapper over v1."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import syn_api.v1.artifacts as art
from syn_api.types import Err

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


# =============================================================================
# Response Models
# =============================================================================


class ArtifactSummaryResponse(BaseModel):
    """Summary of an artifact."""

    id: str
    workflow_id: str | None
    phase_id: str | None
    artifact_type: str
    title: str | None = None
    size_bytes: int = 0
    created_at: str | None = None


class ArtifactResponse(BaseModel):
    """Detailed artifact response."""

    id: str
    workflow_id: str | None
    phase_id: str | None
    session_id: str | None
    artifact_type: str
    is_primary_deliverable: bool = True
    content: str | None = None
    content_type: str = "text/markdown"
    content_hash: str | None = None
    size_bytes: int = 0
    title: str | None = None
    derived_from: list[str] = Field(default_factory=list)
    created_at: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Endpoints
# =============================================================================


@router.get("", response_model=list[ArtifactSummaryResponse])
async def list_artifacts(
    workflow_id: str | None = Query(None, description="Filter by workflow ID"),
    phase_id: str | None = Query(None, description="Filter by phase ID"),
    artifact_type: str | None = Query(None, description="Filter by artifact type"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
) -> list[ArtifactSummaryResponse]:
    """List artifacts with optional filtering."""
    result = await art.list_artifacts(
        workflow_id=workflow_id,
        session_id=None,
        limit=limit,
    )

    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.message)

    items = result.value

    if phase_id:
        items = [a for a in items if a.phase_id == phase_id]
    if artifact_type:
        items = [a for a in items if a.artifact_type == artifact_type]

    return [
        ArtifactSummaryResponse(
            id=a.id,
            workflow_id=a.workflow_id,
            phase_id=a.phase_id,
            artifact_type=a.artifact_type,
            title=a.title,
            size_bytes=a.size_bytes or 0,
            created_at=str(a.created_at) if a.created_at else None,
        )
        for a in items
    ]


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    include_content: bool = Query(True, description="Include artifact content in response"),
) -> ArtifactResponse:
    """Get artifact details by ID."""
    result = await art.get_artifact(artifact_id, include_content=include_content)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    a = result.value

    if include_content and not a.content:
        raise HTTPException(
            status_code=404,
            detail=f"Artifact {artifact_id} content not found in projection.",
        )

    return ArtifactResponse(
        id=a.id,
        workflow_id=a.workflow_id,
        phase_id=a.phase_id,
        session_id=a.session_id,
        artifact_type=a.artifact_type,
        is_primary_deliverable=True,
        content=a.content,
        content_type=a.content_type or "text/markdown",
        size_bytes=a.size_bytes or 0,
        title=a.title,
        derived_from=[],
        created_at=str(a.created_at) if a.created_at else None,
        created_by=None,
        metadata={},
    )


@router.get("/{artifact_id}/content")
async def get_artifact_content(artifact_id: str) -> dict[str, str | int | None]:
    """Get artifact content only (for large artifacts)."""
    result = await art.get_artifact(artifact_id, include_content=True)

    if isinstance(result, Err):
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")

    a = result.value
    return {
        "artifact_id": artifact_id,
        "content": a.content,
        "content_type": a.content_type or "text/markdown",
        "size_bytes": a.size_bytes,
    }
