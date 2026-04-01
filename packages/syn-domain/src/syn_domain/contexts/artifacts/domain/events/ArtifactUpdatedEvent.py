"""ArtifactUpdated event - represents the fact that artifact metadata was updated."""

from __future__ import annotations

from typing import Any

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("ArtifactUpdated", "v1")
class ArtifactUpdatedEvent(DomainEvent):
    """Event emitted when an artifact's metadata is updated.

    Only non-None fields were changed.
    """

    artifact_id: str
    title: str | None = None
    metadata: dict[str, Any] | None = None
    is_primary_deliverable: bool | None = None

    @field_validator("artifact_id")
    @classmethod
    def validate_artifact_id(cls, v: str) -> str:
        """Ensure artifact_id is provided."""
        if not v:
            raise ValueError("artifact_id is required")
        return v
