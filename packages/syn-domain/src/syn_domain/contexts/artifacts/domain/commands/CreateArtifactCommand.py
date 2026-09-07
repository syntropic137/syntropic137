"""CreateArtifact command - creates a new artifact."""

from __future__ import annotations

from typing import Any, Final
from uuid import uuid4

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.artifacts._shared.value_objects import (
    ArtifactType,
    ContentType,
)

#: The shortest artifact content the store will accept.
#:
#: Named rather than spelled inline because a SECOND place now needs the same
#: answer: the phase-completion path has to know that a write is about to be
#: refused BEFORE it is refused, so it can recover the content from the session
#: transcript instead of losing the phase (#1195). Two spellings of "empty"
#: would drift, and the drift would be silent - the recovery would simply stop
#: firing for the case it exists to catch.
#:
#: This is the rule, not a relaxation of it. An empty artifact is still
#: rejected here, and recovery happens before this command is built.
MIN_ARTIFACT_CONTENT_LENGTH: Final[int] = 1


@command("CreateArtifact", "Creates a new artifact storing phase output")
class CreateArtifactCommand(BaseModel):
    """Command to create a new artifact.

    Artifacts store outputs produced by workflow phases.
    """

    model_config = ConfigDict(frozen=True)

    # Target aggregate (auto-generated UUID if not provided)
    aggregate_id: str = Field(default_factory=lambda: str(uuid4()))

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
    content: str = Field(
        ..., description="Artifact content", min_length=MIN_ARTIFACT_CONTENT_LENGTH
    )
    title: str | None = Field(default=None, description="Human-readable title")
    source_path: str | None = Field(
        default=None,
        description="Path this file occupied under the producing workspace's "
        "output directory (issue #988). None means the path is unknown, which "
        "is the case for every artifact created before v5 of ArtifactCreated.",
    )

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
