"""Value objects for artifacts in the workflows bounded context.

Defines immutable data structures used for artifact storage and querying.
"""

from __future__ import annotations

from dataclasses import dataclass


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
