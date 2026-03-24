"""Supabase Storage adapter for production artifact storage.

Provides S3-compatible object storage via Supabase's Storage API.
Used for production deployments where persistent, scalable storage is needed.

Requires:
    - SYN_STORAGE_SUPABASE_URL: Supabase project URL
    - SYN_STORAGE_SUPABASE_KEY: Supabase service role key
    - SYN_STORAGE_BUCKET_NAME: Storage bucket name (default: syn-artifacts)

Usage:
    from syn_adapters.object_storage import SupabaseStorage

    storage = SupabaseStorage(
        supabase_url="https://xxx.supabase.co",
        supabase_key="eyJ...",
        bucket_name="syn-artifacts"
    )
    await storage.upload("test.txt", b"hello")
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
from functools import partial
from typing import TYPE_CHECKING, Any

from syn_adapters.object_storage.protocol import (
    DownloadError,
    ListResult,
    ObjectNotFoundError,
    StorageConfigurationError,
    StorageObject,
    UploadError,
    UploadResult,
)
from syn_adapters.object_storage.supabase_helpers import (
    do_delete as _do_delete,
    do_download as _do_download,
    get_presigned_url as _get_presigned_url,
)
from syn_adapters.object_storage.supabase_queries import (
    get_object_info as _get_object_info,
    list_objects as _list_objects,
)

if TYPE_CHECKING:
    from syn_shared.settings.storage import StorageProvider

logger = logging.getLogger(__name__)


def _do_upload(
    client: Any,
    bucket_name: str,
    key: str,
    content: bytes,
    content_type: str | None,
    metadata: dict[str, str] | None,
) -> UploadResult:
    """Synchronous upload body for Supabase Storage (run in executor).

    Handles content-type detection, metadata encoding, upload, and URL retrieval.
    Raises UploadError on failure so the async caller needs no try/except.

    Args:
        client: Supabase client instance.
        bucket_name: Storage bucket name.
        key: Object key (path) within the bucket.
        content: Raw bytes to store.
        content_type: MIME type. Auto-detected if not provided.
        metadata: Custom metadata (stored as custom headers).

    Returns:
        UploadResult with key, size, and URL.

    Raises:
        UploadError: If upload fails.
    """
    try:
        if content_type is None:
            content_type, _ = mimetypes.guess_type(key)
            content_type = content_type or "application/octet-stream"

        file_options: dict[str, str] = {"content-type": content_type}
        if metadata:
            import json

            file_options["x-upsert-metadata"] = json.dumps(metadata)

        response = client.storage.from_(bucket_name).upload(
            path=key,
            file=content,
            file_options=file_options,
        )

        if hasattr(response, "error") and response.error:
            raise UploadError(f"Supabase upload failed: {response.error}", key=key)

        etag = hashlib.md5(content, usedforsecurity=False).hexdigest()
        url_response = client.storage.from_(bucket_name).get_public_url(key)

        return UploadResult(
            key=key,
            size_bytes=len(content),
            etag=etag,
            url=url_response if isinstance(url_response, str) else None,
        )
    except UploadError:
        raise
    except Exception as e:
        logger.exception("Failed to upload to Supabase: %s", key)
        raise UploadError(f"Failed to upload {key}: {e}", key=key) from e


class SupabaseStorage:
    """Supabase Storage adapter.

    Uses Supabase's Storage API for object storage operations.
    Supabase Storage is S3-compatible and provides:
    - Automatic CDN distribution
    - Row-level security integration
    - Presigned URLs for direct access

    Thread-safe - Supabase client handles connection pooling.
    """

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        bucket_name: str,
    ) -> None:
        """Initialize Supabase storage.

        Args:
            supabase_url: Supabase project URL.
            supabase_key: Supabase service role key.
            bucket_name: Storage bucket name.

        Raises:
            StorageConfigurationError: If supabase package not installed.
        """
        self._supabase_url = supabase_url
        self._supabase_key = supabase_key
        self._bucket_name = bucket_name
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create Supabase client.

        Returns:
            Supabase client instance.

        Raises:
            StorageConfigurationError: If supabase package not installed.
        """
        if self._client is not None:
            return self._client

        try:
            from supabase import create_client

            self._client = create_client(self._supabase_url, self._supabase_key)
            return self._client
        except ImportError as e:
            raise StorageConfigurationError(
                "Supabase package not installed. Install with: pip install supabase"
            ) from e

    @property
    def provider(self) -> StorageProvider:
        """Get the storage provider type."""
        from syn_shared.settings.storage import StorageProvider

        return StorageProvider.SUPABASE

    @property
    def bucket_name(self) -> str:
        """Get the bucket name."""
        return self._bucket_name

    async def upload(
        self,
        key: str,
        content: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResult:
        """Upload content to Supabase Storage.

        Args:
            key: Object key (path) within the bucket.
            content: Raw bytes to store.
            content_type: MIME type. Auto-detected if not provided.
            metadata: Custom metadata (stored as custom headers).

        Returns:
            UploadResult with key, size, and URL.

        Raises:
            UploadError: If upload fails.
        """
        client = self._get_client()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            partial(_do_upload, client, self._bucket_name, key, content, content_type, metadata),
        )

    async def download(self, key: str) -> bytes:
        """Download content from Supabase Storage.

        Args:
            key: Object key (path) to download.

        Returns:
            Raw bytes of the object content.

        Raises:
            ObjectNotFoundError: If object doesn't exist.
            DownloadError: If download fails.
        """
        client = self._get_client()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            partial(_do_download, client, self._bucket_name, key),
        )

    async def delete(self, key: str) -> bool:
        """Delete an object from Supabase Storage.

        Args:
            key: Object key (path) to delete.

        Returns:
            True if object was deleted, False if it didn't exist.
        """
        client = self._get_client()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            partial(_do_delete, client, self._bucket_name, key),
        )

    async def exists(self, key: str) -> bool:
        """Check if an object exists in Supabase Storage.

        Args:
            key: Object key (path) to check.

        Returns:
            True if object exists.
        """
        try:
            info = await self.get_object_info(key)
            return info is not None
        except Exception:
            return False

    async def get_object_info(self, key: str) -> StorageObject | None:
        """Get object metadata without downloading content.

        Args:
            key: Object key (path) to get info for.

        Returns:
            StorageObject with metadata, or None if not found.
        """
        return await _get_object_info(self._get_client, self._bucket_name, key)

    async def list_objects(
        self,
        prefix: str = "",
        *,
        max_keys: int = 1000,
        continuation_token: str | None = None,
    ) -> ListResult:
        """List objects matching a prefix in Supabase Storage.

        Args:
            prefix: Key prefix to filter by.
            max_keys: Maximum objects to return.
            continuation_token: Offset for pagination.

        Returns:
            ListResult with matching objects.
        """
        return await _list_objects(
            self._get_client,
            self._bucket_name,
            prefix,
            max_keys=max_keys,
            continuation_token=continuation_token,
        )

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
            expires_in: Seconds until URL expires.
            for_upload: If True, generate upload URL (not supported).

        Returns:
            Presigned URL string.

        Raises:
            NotImplementedError: If for_upload is True.
        """
        return await _get_presigned_url(
            self._get_client,
            self._bucket_name,
            key,
            expires_in=expires_in,
            for_upload=for_upload,
        )
