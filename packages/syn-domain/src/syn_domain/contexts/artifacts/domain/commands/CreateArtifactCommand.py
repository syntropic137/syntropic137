"""CreateArtifact command - creates a new artifact."""

from __future__ import annotations

from typing import Any

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.artifacts._shared.value_objects import (
    ArtifactType,
    ContentType,
)


@command("CreateArtifact", "Creates a new artifact storing phase output")
class CreateArtifactCommand(BaseModel):
    """Command to create a new artifact.

    Artifacts store outputs produced by workflow phases.
    """

    model_config = ConfigDict(frozen=True)

    # Target aggregate (generated if not provided)
    aggregate_id: str | None = None

    # Context - links artifact to workflow execution
    workflow_id: str = Field(..., description="Workflow this artifact belongs to")
    phase_id: str = Field(..., description="Phase that produced this artifact")
    execution_id: str | None = Field(
        default=None, description="Execution run that produced this artifact"
    )
    session_id: str | None = Field(default=None, description="Session that produced this artifact")

    # Type
    artifact_type: ArtifactType = Field(..., description="Type of artifact")
    content_type: ContentType | None = Field(
        default=ContentType.TEXT_MARKDOWN, description="MIME type of content"
    )

    # Content
    content: str = Field(..., description="Artifact content", min_length=1)
    title: str | None = Field(default=None, description="Human-readable title")

    # Storage (ADR-012: Two-tier storage)
    storage_uri: str | None = Field(
        default=None,
        description="URI to content in object storage (e.g., s3://bucket/key). "
        "If None, content is stored only in event store.",
    )

    # Classification
    is_primary_deliverable: bool = Field(
        default=True, description="Whether this is the primary phase output"
    )

    # Lineage
    derived_from: list[str] | None = Field(
        default=None, description="Parent artifact IDs this was derived from"
    )

    # Metadata
    metadata: dict[str, Any] | None = None
