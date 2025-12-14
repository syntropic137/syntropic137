"""ArtifactUploaded event - represents the fact that an artifact was uploaded to storage."""

from __future__ import annotations

from dataclasses import field
from datetime import UTC, datetime
from typing import Any

from event_sourcing import DomainEvent, event


@event("ArtifactUploaded", "v1")
class ArtifactUploadedEvent(DomainEvent):
    """Event emitted when an artifact is uploaded to object storage.

    This event tracks the storage of artifacts for:
    - Audit trail of artifact storage
    - Analytics on storage usage
    - Triggering downstream processes (e.g., notifications)
    """

    # Bundle identity
    bundle_id: str
    """Unique identifier for the artifact bundle."""

    # Context
    workflow_id: str | None = None
    """Workflow that produced these artifacts."""

    session_id: str | None = None
    """Session that produced these artifacts."""

    phase_id: str | None = None
    """Phase that produced these artifacts."""

    # Storage details
    storage_provider: str
    """Storage provider used (e.g., 'local', 'supabase')."""

    storage_prefix: str
    """Key prefix where artifacts were stored."""

    bucket_name: str | None = None
    """Storage bucket name (for cloud storage)."""

    # Content summary
    file_count: int
    """Number of files in the bundle."""

    total_size_bytes: int
    """Total size of all files in bytes."""

    file_keys: list[str] = field(default_factory=list)
    """List of storage keys for uploaded files."""

    # Timing
    upload_duration_ms: float = 0.0
    """Time taken to upload in milliseconds."""

    uploaded_at: str | None = None
    """ISO timestamp when upload completed."""

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata about the upload."""

    def __post_init__(self) -> None:
        """Set uploaded_at if not provided."""
        if self.uploaded_at is None:
            object.__setattr__(self, "uploaded_at", datetime.now(UTC).isoformat())
