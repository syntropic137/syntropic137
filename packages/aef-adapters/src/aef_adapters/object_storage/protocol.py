"""Object storage protocol - interface for storing and retrieving artifacts.

Provides a protocol-based abstraction for object storage backends,
supporting both local filesystem (development) and Supabase Storage (production).

See ADR-012: Artifact Storage

Usage:
    from aef_adapters.object_storage import get_storage

    storage = await get_storage()

    # Upload an artifact
    key = await storage.upload("artifacts/report.md", content)

    # Download an artifact
    content = await storage.download("artifacts/report.md")

    # List artifacts
    objects = await storage.list_objects("artifacts/")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aef_shared.settings.storage import StorageProvider


@dataclass(frozen=True)
class StorageObject:
    """Metadata for an object in storage.

    Represents a single file/object without its content.
    """

    key: str
    """Object key (path) within the bucket."""

    size_bytes: int
    """Size of the object in bytes."""

    content_type: str | None = None
    """MIME type of the object (e.g., 'text/markdown')."""

    etag: str | None = None
    """Entity tag for versioning/caching (typically content hash)."""

    last_modified: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When the object was last modified."""

    metadata: dict[str, str] = field(default_factory=dict)
    """Custom metadata attached to the object."""


@dataclass(frozen=True)
class UploadResult:
    """Result of an upload operation."""

    key: str
    """Object key where content was stored."""

    size_bytes: int
    """Size of the uploaded content in bytes."""

    etag: str | None = None
    """Entity tag assigned by storage backend."""

    url: str | None = None
    """Public URL if object is publicly accessible."""


@dataclass(frozen=True)
class ListResult:
    """Result of a list operation with pagination support."""

    objects: list[StorageObject]
    """Objects matching the prefix."""

    is_truncated: bool = False
    """Whether there are more results (pagination)."""

    next_continuation_token: str | None = None
    """Token to fetch next page of results."""

    prefix: str | None = None
    """The prefix that was searched."""


@runtime_checkable
class StorageProtocol(Protocol):
    """Protocol for object storage implementations.

    All implementations must support:
    - Upload/download operations
    - Listing objects by prefix
    - Deletion
    - Checking existence

    Optional features:
    - Presigned URLs for direct access
    - Content type detection
    - Custom metadata
    """

    @property
    def provider(self) -> StorageProvider:
        """Get the storage provider type."""
        ...

    @property
    def bucket_name(self) -> str:
        """Get the bucket/container name."""
        ...

    async def upload(
        self,
        key: str,
        content: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResult:
        """Upload content to storage.

        Args:
            key: Object key (path) within the bucket.
                 Example: "workflows/123/artifacts/report.md"
            content: Raw bytes to store.
            content_type: MIME type. Auto-detected if not provided.
            metadata: Custom metadata to attach.

        Returns:
            UploadResult with key, size, and optional URL.

        Raises:
            StorageError: If upload fails.
        """
        ...

    async def download(self, key: str) -> bytes:
        """Download content from storage.

        Args:
            key: Object key (path) to download.

        Returns:
            Raw bytes of the object content.

        Raises:
            ObjectNotFoundError: If object doesn't exist.
            StorageError: If download fails.
        """
        ...

    async def delete(self, key: str) -> bool:
        """Delete an object from storage.

        Args:
            key: Object key (path) to delete.

        Returns:
            True if object was deleted, False if it didn't exist.

        Raises:
            StorageError: If deletion fails for other reasons.
        """
        ...

    async def exists(self, key: str) -> bool:
        """Check if an object exists.

        Args:
            key: Object key (path) to check.

        Returns:
            True if object exists, False otherwise.
        """
        ...

    async def get_object_info(self, key: str) -> StorageObject | None:
        """Get metadata for an object without downloading content.

        Args:
            key: Object key (path) to get info for.

        Returns:
            StorageObject with metadata, or None if not found.
        """
        ...

    async def list_objects(
        self,
        prefix: str = "",
        *,
        max_keys: int = 1000,
        continuation_token: str | None = None,
    ) -> ListResult:
        """List objects matching a prefix.

        Args:
            prefix: Key prefix to filter by.
                    Example: "workflows/123/" lists all objects in that workflow.
            max_keys: Maximum objects to return per call.
            continuation_token: Token from previous call for pagination.

        Returns:
            ListResult with matching objects and pagination info.
        """
        ...

    async def get_presigned_url(
        self,
        key: str,
        *,
        expires_in: int = 3600,
        for_upload: bool = False,
    ) -> str:
        """Get a presigned URL for direct access.

        Args:
            key: Object key (path).
            expires_in: Seconds until URL expires (default: 1 hour).
            for_upload: If True, URL allows PUT; otherwise GET only.

        Returns:
            Presigned URL string.

        Raises:
            NotImplementedError: If backend doesn't support presigned URLs.
        """
        ...


# =============================================================================
# EXCEPTIONS
# =============================================================================


class StorageError(Exception):
    """Base exception for storage operations."""

    def __init__(self, message: str, key: str | None = None):
        self.key = key
        super().__init__(message)


class ObjectNotFoundError(StorageError):
    """Object was not found in storage."""

    def __init__(self, key: str):
        super().__init__(f"Object not found: {key}", key=key)


class UploadError(StorageError):
    """Upload operation failed."""

    pass


class DownloadError(StorageError):
    """Download operation failed."""

    pass


class StorageConfigurationError(StorageError):
    """Storage is not properly configured."""

    pass
