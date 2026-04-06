"""Value objects for artifacts in the workflows bounded context.

Defines immutable data structures used for artifact storage and querying.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ArtifactUploadResult:
    """Result of uploading artifact content to object storage.

    Returned by ArtifactContentStoragePort.upload() to provide
    the storage location and size information.
    """

    storage_uri: str
    """Full URI to the stored artifact (e.g., 's3://bucket/artifacts/artifact-123.md')."""

    size_bytes: int
    """Size of the uploaded content in bytes."""


@dataclass(frozen=True)
class ArtifactSummary:
    """Summary information about an artifact from the projection layer.

    Used by ArtifactQueryServicePort to return artifact metadata
    without loading full content.
    """

    artifact_id: str
    """Unique identifier for the artifact."""

    phase_id: str
    """Phase that created this artifact."""

    execution_id: str
    """Execution run that created this artifact."""

    workflow_id: str
    """Workflow this artifact belongs to."""

    artifact_type: str
    """Type/category of artifact (e.g., 'research_summary', 'implementation_plan')."""

    storage_uri: str | None
    """URI to artifact content in object storage, if stored externally."""

    size_bytes: int | None
    """Size of artifact content in bytes."""

    created_at: datetime
    """When the artifact was created."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata about the artifact."""
