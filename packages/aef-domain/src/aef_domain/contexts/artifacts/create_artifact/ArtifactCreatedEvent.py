"""ArtifactCreated event - represents the fact that an artifact was created."""

from __future__ import annotations

from typing import Any

from event_sourcing import DomainEvent, event

from aef_domain.contexts.artifacts._shared.value_objects import (  # noqa: TC001
    ArtifactType,
    ContentType,
)


@event("ArtifactCreated", "v1")
class ArtifactCreatedEvent(DomainEvent):
    """Event emitted when an artifact is created."""

    # Identity
    artifact_id: str

    # Context
    workflow_id: str
    phase_id: str
    session_id: str | None = None

    # Type
    artifact_type: ArtifactType
    content_type: ContentType

    # Content
    content: str
    content_hash: str
    size_bytes: int
    title: str | None = None

    # Classification
    is_primary_deliverable: bool = True

    # Lineage
    derived_from: list[str] = []  # noqa: RUF012

    # Metadata
    metadata: dict[str, Any] = {}  # noqa: RUF012
