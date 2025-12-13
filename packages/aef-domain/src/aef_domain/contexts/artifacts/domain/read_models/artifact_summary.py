"""Read model for artifact list views."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ArtifactSummary:
    """Read model for artifact list view.

    This is a lightweight DTO optimized for listing artifacts.
    """

    id: str
    """Unique identifier for the artifact."""

    workflow_id: str
    """ID of the workflow this artifact belongs to."""

    execution_id: str | None
    """ID of the execution run that created this artifact (v2)."""

    session_id: str | None
    """ID of the session that created this artifact."""

    phase_id: str | None
    """ID of the phase this artifact was created in."""

    artifact_type: str
    """Type of artifact (e.g., 'code', 'document', 'data')."""

    name: str
    """Display name of the artifact."""

    created_at: datetime | str | None
    """When the artifact was created (datetime or ISO string)."""

    size_bytes: int = 0
    """Size of the artifact content in bytes."""

    content: str | None = None
    """The artifact content (stored for retrieval)."""

    content_hash: str | None = None
    """Hash of the content for integrity verification."""

    @classmethod
    def from_dict(cls, data: dict) -> "ArtifactSummary":
        """Create from dictionary data."""
        return cls(
            id=data["id"],
            workflow_id=data["workflow_id"],
            execution_id=data.get("execution_id"),  # v2 field
            session_id=data.get("session_id"),
            phase_id=data.get("phase_id"),
            artifact_type=data.get("artifact_type", ""),
            name=data.get("name", ""),
            created_at=data.get("created_at"),
            size_bytes=data.get("size_bytes", 0),
            content=data.get("content"),
            content_hash=data.get("content_hash"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        # Handle created_at which could be datetime or already a string
        created_at_str = None
        if self.created_at:
            if isinstance(self.created_at, str):
                created_at_str = self.created_at
            else:
                created_at_str = self.created_at.isoformat()

        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,  # v2 field
            "session_id": self.session_id,
            "phase_id": self.phase_id,
            "artifact_type": self.artifact_type,
            "name": self.name,
            "created_at": created_at_str,
            "size_bytes": self.size_bytes,
            "content": self.content,
            "content_hash": self.content_hash,
        }
