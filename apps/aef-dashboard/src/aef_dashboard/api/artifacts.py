"""Artifact API endpoints.

ARCHITECTURE NOTE: Artifact Storage
===================================
Currently, artifact storage is split:
- **Metadata** (id, title, type, phase_id) → PostgreSQL (via projections)
- **Content** (actual file content) → Filesystem (.aef-workspaces/)

This is a **development-only** setup. For production:
- Content should be stored in database or object storage (S3/GCS)
- This allows the UI to run independently of execution hosts
- See: docs/adrs/ADR-012-artifact-storage.md (to be created)

The _load_artifact_content() function reads from filesystem as a temporary
solution. Replace with database/object storage queries for production.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
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


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    """Parse datetime from string or datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


# Base path for workspace artifacts (DEVELOPMENT ONLY - see module docstring)
_WORKSPACE_BASE = Path.cwd() / ".aef-workspaces"

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _domain_artifact_to_api(artifact: DomainArtifactSummary) -> ArtifactSummary:
    """Convert domain ArtifactSummary to API ArtifactSummary."""
    return ArtifactSummary(
        id=artifact.id,
        workflow_id=artifact.workflow_id,
        phase_id=artifact.phase_id,
        artifact_type=artifact.artifact_type,
        title=artifact.name,
        size_bytes=artifact.size_bytes,
        created_at=_parse_datetime(artifact.created_at),
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
    include_content: bool = Query(True, description="Include artifact content in response"),
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

    # Get content from projection first (stored in event store)
    content = artifact.content if include_content else None
    size_bytes = artifact.size_bytes

    # Fallback to filesystem if no content in projection (legacy artifacts)
    if include_content and not content:
        content, size_bytes = _load_artifact_content(artifact_id, artifact.phase_id)

    return ArtifactResponse(
        id=artifact.id,
        workflow_id=artifact.workflow_id,
        phase_id=artifact.phase_id,
        session_id=artifact.session_id,
        artifact_type=artifact.artifact_type,
        is_primary_deliverable=True,
        content=content,
        content_type="text/markdown",
        content_hash=artifact.content_hash,
        size_bytes=size_bytes,
        title=artifact.name,
        derived_from=[],
        created_at=_parse_datetime(artifact.created_at),
        created_by=None,
        metadata={},
    )


@router.get("/{artifact_id}/content")
async def get_artifact_content(artifact_id: str) -> dict[str, str | int | None]:
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

    # Get content from projection first
    content = artifact.content
    size_bytes = artifact.size_bytes

    # Fallback to filesystem if no content in projection
    if not content:
        content, size_bytes = _load_artifact_content(artifact_id, artifact.phase_id)

    return {
        "artifact_id": artifact_id,
        "content": content,
        "content_type": "text/markdown",
        "size_bytes": size_bytes,
    }


def _load_artifact_content(artifact_id: str, phase_id: str | None) -> tuple[str | None, int]:
    """Load artifact content from workspace files.

    Searches for artifact content in the .aef-workspaces directory structure.

    Args:
        artifact_id: The artifact ID to find.
        phase_id: The phase ID (e.g., "phase-1").

    Returns:
        Tuple of (content, size_bytes). Content is None if not found.
    """
    if not _WORKSPACE_BASE.exists():
        return None, 0

    # Search strategy:
    # 1. Look for phase output file directly (e.g., phase-1_output.md)
    # 2. Look in artifact subdirectories
    # 3. Look for any markdown file in the phase directory

    for execution_dir in _WORKSPACE_BASE.iterdir():
        if not execution_dir.is_dir():
            continue

        # Try direct phase output
        if phase_id:
            phase_output = execution_dir / phase_id / f"{phase_id}_output.md"
            if phase_output.exists():
                try:
                    content = phase_output.read_text(encoding="utf-8")
                    return content, len(content.encode("utf-8"))
                except Exception:
                    pass

            # Check artifacts directory for this artifact ID
            artifacts_dir = execution_dir / phase_id / ".context" / "artifacts" / artifact_id
            if artifacts_dir.exists():
                for md_file in artifacts_dir.glob("*.md"):
                    try:
                        content = md_file.read_text(encoding="utf-8")
                        return content, len(content.encode("utf-8"))
                    except Exception:
                        pass

            # Look for any markdown in the phase directory
            phase_dir = execution_dir / phase_id
            if phase_dir.exists():
                for md_file in phase_dir.glob("*.md"):
                    if md_file.name.startswith("."):
                        continue
                    try:
                        content = md_file.read_text(encoding="utf-8")
                        return content, len(content.encode("utf-8"))
                    except Exception:
                        pass

    return None, 0
