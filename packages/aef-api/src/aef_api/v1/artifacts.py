"""Artifact operations — list, create, and upload artifacts.

Maps to the artifacts context in aef-domain.

Stub implementation for Phase 1 — complete signatures and types,
with TODO markers pointing to domain slices.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aef_api.types import ArtifactError, ArtifactSummary, Err, Result

if TYPE_CHECKING:
    from aef_api.auth import AuthContext


async def list_artifacts(
    workflow_id: str | None = None,
    session_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    auth: AuthContext | None = None,
) -> Result[list[ArtifactSummary], ArtifactError]:
    """List artifacts, optionally filtered by workflow or session.

    Args:
        workflow_id: Filter by workflow ID.
        session_id: Filter by session ID.
        limit: Maximum results to return.
        offset: Pagination offset.
        auth: Optional authentication context.

    Returns:
        Ok(list[ArtifactSummary]) on success, Err(ArtifactError) on failure.
    """
    # TODO(#92): Implement — maps to domain slice artifacts/list_artifacts
    # Wire: get_projection_manager().artifact_list → ArtifactListProjection
    return Err(
        ArtifactError.NOT_IMPLEMENTED,
        message="list_artifacts not yet implemented — see #92 Phase 1",
    )


async def create_artifact(
    workflow_id: str,
    artifact_type: str,
    title: str,
    content: str,
    phase_id: str | None = None,
    session_id: str | None = None,
    content_type: str = "text/markdown",
    auth: AuthContext | None = None,
) -> Result[str, ArtifactError]:
    """Create a new artifact.

    Args:
        workflow_id: The workflow this artifact belongs to.
        artifact_type: Type of artifact (e.g., "code", "document", "report").
        title: Human-readable title.
        content: Artifact content.
        phase_id: Optional phase within the workflow.
        session_id: Optional session that created this artifact.
        content_type: MIME type of the content.
        auth: Optional authentication context.

    Returns:
        Ok(artifact_id) on success, Err(ArtifactError) on failure.
    """
    # TODO(#92): Implement — maps to domain slice artifacts/create_artifact
    # Wire: get_artifact_repository() → ArtifactAggregate.create()
    return Err(
        ArtifactError.NOT_IMPLEMENTED,
        message="create_artifact not yet implemented — see #92 Phase 1",
    )


async def upload_artifact(
    artifact_id: str,
    data: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    auth: AuthContext | None = None,
) -> Result[str, ArtifactError]:
    """Upload binary content for an existing artifact.

    Args:
        artifact_id: The artifact to upload content for.
        data: Binary content to upload.
        filename: Original filename.
        content_type: MIME type of the uploaded content.
        auth: Optional authentication context.

    Returns:
        Ok(storage_url) on success, Err(ArtifactError) on failure.
    """
    # TODO(#92): Implement — maps to artifact content storage (MinIO)
    # Wire: get_artifact_storage() → ArtifactContentStoragePort.upload()
    return Err(
        ArtifactError.NOT_IMPLEMENTED,
        message="upload_artifact not yet implemented — see #92 Phase 1",
    )
