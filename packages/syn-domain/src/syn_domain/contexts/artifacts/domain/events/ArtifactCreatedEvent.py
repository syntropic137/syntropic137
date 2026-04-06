"""ArtifactCreated event - represents the fact that an artifact was created."""

from __future__ import annotations

from typing import Any

from event_sourcing import DomainEvent, event

from syn_domain.contexts.artifacts._shared.value_objects import (
    ArtifactType,
    ContentType,
)


@event("ArtifactCreated", "v3")
class ArtifactCreatedEvent(DomainEvent):
    """Event emitted when an artifact is created.

    v2: Added execution_id to link artifacts to specific workflow execution runs.
    v3: Added storage_uri for two-tier storage (ADR-012).
    """

    # Identity
    artifact_id: str

    # Context - links artifact to workflow execution
    workflow_id: str
    phase_id: str
    execution_id: str | None = None  # NEW in v2: Links to WorkflowExecution
    session_id: str | None = None

    # Type
    artifact_type: ArtifactType
    content_type: ContentType

    # Content
    content: str
    content_hash: str
    size_bytes: int
    title: str | None = None

    # Storage (ADR-012: Two-tier storage)
    storage_uri: str | None = None  # NEW in v3: URI to object storage

    # Classification
    is_primary_deliverable: bool = True

    # Lineage
    derived_from: list[str] = []

    # Metadata
    metadata: dict[str, Any] = {}
