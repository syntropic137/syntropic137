"""Local filesystem storage adapter for development.

Provides a simple filesystem-based storage implementation for
local development and testing. Uses the configured local_path
from StorageSettings.

Usage:
    from syn_adapters.object_storage import LocalStorage

    storage = LocalStorage(base_path=Path(".artifacts"))
    await storage.upload("test.txt", b"hello")
    content = await storage.download("test.txt")
"""

from __future__ import annotations

import asyncio
import hashlib
from functools import partial
from pathlib import Path  # noqa: TC003 - used at runtime
from typing import TYPE_CHECKING

from syn_adapters.object_storage.local_helpers import (
    get_object_info as _get_object_info,
)
from syn_adapters.object_storage.local_helpers import (
    get_presigned_url as _get_presigned_url,
)
from syn_adapters.object_storage.local_helpers import (
    list_objects as _list_objects,
)
from syn_adapters.object_storage.protocol import (
    DownloadError,
    ListResult,
    ObjectNotFoundError,
    StorageObject,
    UploadError,
    UploadResult,
)

if TYPE_CHECKING:
    from syn_shared.settings.storage import StorageProvider


def _sync_write_file(file_path: Path, content: bytes, key: str) -> UploadResult:
    """Write bytes to a file; creates parent dirs; returns UploadResult.

    Wraps failures in UploadError so the async caller needs no try/except.
    """
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        etag = hashlib.md5(content, usedforsecurity=False).hexdigest()
        return UploadResult(key=key, size_bytes=len(content), etag=etag, url=f"file://{file_path}")
    except ValueError:
        raise
    except Exception as e:
        raise UploadError(f"Failed to upload {key}: {e}", key=key) from e


def _sync_read_file(file_path: Path, key: str) -> bytes:
    """Read bytes from a file; raises ObjectNotFoundError or DownloadError."""
    try:
        if not file_path.exists():
            raise ObjectNotFoundError(key)
        return file_path.read_bytes()
    except ObjectNotFoundError:
        raise
    except ValueError as e:
        raise ObjectNotFoundError(key) from e
    except Exception as e:
        raise DownloadError(f"Failed to download {key}: {e}", key=key) from e


def _sync_delete_file(file_path: Path) -> bool:
    """Delete a file; returns True if deleted, False if it did not exist."""
    if not file_path.exists():
        return False
    file_path.unlink()
    return True


class LocalStorage:
    """Local filesystem storage adapter.

    Stores objects as files on the local filesystem.
    Keys are mapped to file paths under the base directory.

    Thread-safe via asyncio executors for file operations.
    """

    def __init__(self, base_path: Path) -> None:
        """Initialize local storage.

        Args:
            base_path: Base directory for storing objects.
                      Will be created if it doesn't exist.
        """
        self._base_path = base_path.resolve()
        self._base_path.mkdir(parents=True, exist_ok=True)

    @property
    def provider(self) -> StorageProvider:
        """Get the storage provider type."""
        from syn_shared.settings.storage import StorageProvider

        return StorageProvider.LOCAL

    @property
    def bucket_name(self) -> str:
        """Get the bucket name (base path for local storage)."""
        return str(self._base_path)

    def _resolve_path(self, key: str) -> Path:
        """Resolve a key to a full file path.

        Validates that the path stays within the base directory
        to prevent path traversal attacks.

        Args:
            key: Object key (path).

        Returns:
            Resolved absolute path.

        Raises:
            ValueError: If key would escape base directory.
        """
        # Normalize key - remove leading slashes
        clean_key = key.lstrip("/")
        full_path = (self._base_path / clean_key).resolve()

        # Security: Ensure path doesn't escape base directory
        if not str(full_path).startswith(str(self._base_path)):
            msg = f"Invalid key - path traversal detected: {key}"
            raise ValueError(msg)

        return full_path

    async def upload(
        self,
        key: str,
        content: bytes,
        *,
        content_type: str | None = None,  # noqa: ARG002 - protocol signature
        metadata: dict[str, str] | None = None,  # noqa: ARG002 - protocol signature
    ) -> UploadResult:
        """Upload content to local filesystem.

        Args:
            key: Object key (relative path).
            content: Raw bytes to store.
            content_type: MIME type (not used for local storage).
            metadata: Custom metadata (not used for local storage).

        Returns:
            UploadResult with key and size.
        """
        file_path = self._resolve_path(key)
        return await asyncio.get_event_loop().run_in_executor(
            None, partial(_sync_write_file, file_path, content, key)
        )

    async def download(self, key: str) -> bytes:
        """Download content from local filesystem.

        Args:
            key: Object key (relative path).

        Returns:
            Raw bytes of the file content.

        Raises:
            ObjectNotFoundError: If file doesn't exist.
        """
        file_path = self._resolve_path(key)
        return await asyncio.get_event_loop().run_in_executor(
            None, partial(_sync_read_file, file_path, key)
        )

    async def delete(self, key: str) -> bool:
        """Delete a file from local filesystem.

        Args:
            key: Object key (relative path).

        Returns:
            True if file was deleted, False if it didn't exist.
        """
        try:
            file_path = self._resolve_path(key)
        except ValueError:
            return False
        return await asyncio.get_event_loop().run_in_executor(
            None, partial(_sync_delete_file, file_path)
        )

    async def exists(self, key: str) -> bool:
        """Check if a file exists.

        Args:
            key: Object key (relative path).

        Returns:
            True if file exists.
        """
        try:
            file_path = self._resolve_path(key)
            return file_path.exists() and file_path.is_file()
        except ValueError:
            return False

    async def get_object_info(self, key: str) -> StorageObject | None:
        """Get file metadata without reading content.

        Args:
            key: Object key (relative path).

        Returns:
            StorageObject with metadata, or None if not found.
        """
        return await _get_object_info(self._resolve_path, key)

    async def list_objects(
        self,
        prefix: str = "",
        *,
        max_keys: int = 1000,
        continuation_token: str | None = None,  # noqa: ARG002 - not implemented for local
    ) -> ListResult:
        """List files matching a prefix.

        Args:
            prefix: Key prefix to filter by.
            max_keys: Maximum files to return.
            continuation_token: Not implemented for local storage.

        Returns:
            ListResult with matching files.
        """
        return await _list_objects(
            self._base_path,
            self._resolve_path,
            prefix,
            max_keys=max_keys,
        )

    async def get_presigned_url(
        self,
        key: str,
        *,
        expires_in: int = 3600,  # noqa: ARG002 - not applicable for local
        for_upload: bool = False,  # noqa: ARG002 - not applicable for local
    ) -> str:
        """Get a file:// URL for local access.

        Note: This returns a file:// URL, not a presigned URL.
        Presigned URLs are not applicable to local filesystem.

        Args:
            key: Object key (relative path).
            expires_in: Not applicable for local storage.
            for_upload: Not applicable for local storage.

        Returns:
            file:// URL to the local file.
        """
        return await _get_presigned_url(self._resolve_path, key)
