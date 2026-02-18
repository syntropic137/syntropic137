"""MinIO artifact storage adapter - production implementation.

Stores artifact content in MinIO (S3-compatible object storage).
Uses the existing MinioStorage from syn_adapters.object_storage.

Storage key format:
    artifacts/{workflow_id}/{execution_id}/{artifact_id}.md

See ADR-012: Artifact Storage Architecture
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

# Import StorageResult from domain (not local definition)
from syn_domain.contexts.artifacts.ports import StorageResult

if TYPE_CHECKING:
    from syn_adapters.object_storage.minio import MinioStorage

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when a storage operation fails."""

    pass


class ArtifactNotFoundError(Exception):
    """Raised when an artifact is not found in storage."""

    def __init__(self, artifact_id: str) -> None:
        super().__init__(f"Artifact not found: {artifact_id}")


class MinioArtifactStorage:
    """MinIO-backed artifact storage for production use.

    Implements ArtifactContentStoragePort using MinIO (S3-compatible).

    Storage organization:
        syn-artifacts/
        └── artifacts/
            └── {workflow_id}/
                └── {execution_id}/
                    └── {artifact_id}.md

    Thread-safe for concurrent uploads.

    Usage:
        storage = MinioArtifactStorage(minio_client)
        result = await storage.upload("artifact-123", b"content", workflow_id="wf-1")
    """

    def __init__(
        self,
        minio_storage: MinioStorage,
        *,
        prefix: str = "artifacts",
    ) -> None:
        """Initialize MinIO artifact storage.

        Args:
            minio_storage: Configured MinioStorage instance
            prefix: Key prefix for all artifacts (default: 'artifacts')
        """
        self._storage = minio_storage
        self._prefix = prefix

    def _build_key(
        self,
        artifact_id: str,
        workflow_id: str | None = None,
        execution_id: str | None = None,
    ) -> str:
        """Build storage key for an artifact.

        Format: {prefix}/{workflow_id}/{execution_id}/{artifact_id}.md
        """
        parts = [self._prefix]
        if workflow_id:
            parts.append(workflow_id)
        if execution_id:
            parts.append(execution_id)
        parts.append(f"{artifact_id}.md")
        return "/".join(parts)

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
        """Upload artifact content to MinIO."""
        key = self._build_key(artifact_id, workflow_id, execution_id)
        content_hash = hashlib.sha256(content).hexdigest()

        # Build metadata for S3
        s3_metadata = {
            "artifact_id": artifact_id,
            "content_hash": content_hash,
        }
        if phase_id:
            s3_metadata["phase_id"] = phase_id
        if execution_id:
            s3_metadata["execution_id"] = execution_id
        if metadata:
            # Flatten metadata for S3 (must be string values)
            for k, v in metadata.items():
                s3_metadata[k] = str(v)

        try:
            result = await self._storage.upload(
                key,
                content,
                content_type=content_type,
                metadata=s3_metadata,
            )

            storage_uri = f"s3://{self._storage._bucket_name}/{key}"

            logger.info(
                "Artifact uploaded to MinIO",
                extra={
                    "artifact_id": artifact_id,
                    "storage_uri": storage_uri,
                    "size_bytes": len(content),
                },
            )

            return StorageResult(
                storage_uri=storage_uri,
                content_hash=content_hash,
                size_bytes=len(content),
                metadata={
                    "key": result.key,
                    "etag": result.etag,
                    **s3_metadata,
                },
            )
        except Exception as e:
            logger.error(
                "Failed to upload artifact to MinIO",
                extra={"artifact_id": artifact_id, "error": str(e)},
            )
            raise StorageError(f"Failed to upload artifact {artifact_id}: {e}") from e

    async def download(self, artifact_id: str) -> bytes:
        """Download artifact content from MinIO.

        Note: This searches for the artifact key. For faster lookups,
        store the full key in the aggregate's storage_uri field.
        """
        # Simple key lookup (assumes artifact_id is unique)
        key = self._build_key(artifact_id)

        try:
            return await self._storage.download(key)
        except Exception as e:
            raise ArtifactNotFoundError(artifact_id) from e

    async def download_by_uri(self, storage_uri: str) -> bytes:
        """Download artifact by its full storage URI.

        Args:
            storage_uri: Full URI (e.g., s3://bucket/key)

        Returns:
            Artifact content as bytes
        """
        # Parse s3://bucket/key format
        if storage_uri.startswith("s3://"):
            # Remove s3://bucket/ prefix
            parts = storage_uri[5:].split("/", 1)
            if len(parts) == 2:
                key = parts[1]
                return await self._storage.download(key)

        raise ArtifactNotFoundError(storage_uri)

    async def delete(self, artifact_id: str) -> None:
        """Delete artifact from MinIO."""
        key = self._build_key(artifact_id)
        try:
            await self._storage.delete(key)
            logger.info("Artifact deleted from MinIO", extra={"artifact_id": artifact_id})
        except Exception as e:
            logger.warning(
                "Failed to delete artifact (may not exist)",
                extra={"artifact_id": artifact_id, "error": str(e)},
            )

    async def exists(self, artifact_id: str) -> bool:
        """Check if artifact exists in MinIO."""
        key = self._build_key(artifact_id)
        try:
            await self._storage.download(key)
            return True
        except Exception:
            return False
