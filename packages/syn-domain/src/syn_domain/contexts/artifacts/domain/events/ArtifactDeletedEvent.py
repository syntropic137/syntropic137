"""ArtifactDeleted event - represents the fact that an artifact was soft-deleted."""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("ArtifactDeleted", "v1")
class ArtifactDeletedEvent(DomainEvent):
    """Event emitted when an artifact is soft-deleted.

    Deleted artifacts are hidden from listings but preserved
    in the event store for historical reference.
    """

    artifact_id: str
    deleted_by: str = ""

    @field_validator("artifact_id")
    @classmethod
    def validate_artifact_id(cls, v: str) -> str:
        """Ensure artifact_id is provided."""
        if not v:
            raise ValueError("artifact_id is required")
        return v
