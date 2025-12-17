"""Artifact content storage port - interface for storing artifact content.

This port defines how the domain stores large artifact content externally.
The domain stores metadata in event store, content in object storage.

Implementations:
- MinioArtifactStorage: Production/development (S3-compatible)
- InMemoryArtifactStorage: Unit tests ONLY (throws if not test env)

Usage:
    # In WorkflowExecutionEngine (injected via DI)
    async def _create_artifact(self, ...):
        # 1. Store content in object storage
        result = await self._artifact_storage.upload(
            artifact_id=artifact_id,
            content=content.encode(),
            metadata={"phase_id": phase_id, ...}
        )

        # 2. Store metadata + storage_uri in event store
        command = CreateArtifactCommand(
            storage_uri=result.storage_uri,
            ...
        )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class StorageResult:
    """Result of an artifact upload operation.

    Contains the storage URI and metadata about the upload.
    """

    storage_uri: str
    """URI where the artifact is stored (e.g., s3://bucket/key)."""

    content_hash: str
    """SHA-256 hash of the content for integrity verification."""

    size_bytes: int
    """Size of the uploaded content in bytes."""

    uploaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When the upload completed."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata returned by storage provider."""


@runtime_checkable
class ArtifactContentStoragePort(Protocol):
    """Port for storing artifact content in external storage.

    This is a domain port - implementations are in the adapters layer.
    The domain doesn't know about MinIO, S3, or filesystem details.

    Contract:
        - upload() stores content and returns a StorageResult
        - download() retrieves content by artifact_id
        - delete() removes content (for cleanup)
        - All operations are async

    Thread Safety:
        Implementations must be thread-safe for concurrent uploads.
    """

    async def upload(
        self,
        artifact_id: str,
        content: bytes,
        *,
        workflow_id: str | None = None,
        phase_id: str | None = None,
        execution_id: str | None = None,
        content_type: str = "text/markdown",
        metadata: dict[str, Any] | None = None,
    ) -> StorageResult:
        """Upload artifact content to storage.

        Args:
            artifact_id: Unique artifact identifier (used in storage key)
            content: Raw bytes to store
            workflow_id: Parent workflow ID (for path organization)
            phase_id: Phase that produced this artifact
            execution_id: Execution run ID
            content_type: MIME type of the content
            metadata: Additional metadata to store with artifact

        Returns:
            StorageResult with storage_uri and upload details

        Raises:
            StorageError: If upload fails
        """
        ...

    async def download(self, artifact_id: str) -> bytes:
        """Download artifact content from storage.

        Args:
            artifact_id: The artifact ID to download

        Returns:
            Raw bytes of the artifact content

        Raises:
            ArtifactNotFoundError: If artifact doesn't exist
            StorageError: If download fails
        """
        ...

    async def delete(self, artifact_id: str) -> None:
        """Delete artifact content from storage.

        Args:
            artifact_id: The artifact ID to delete

        Raises:
            StorageError: If deletion fails (not raised if already deleted)
        """
        ...

    async def exists(self, artifact_id: str) -> bool:
        """Check if artifact exists in storage.

        Args:
            artifact_id: The artifact ID to check

        Returns:
            True if artifact exists, False otherwise
        """
        ...

