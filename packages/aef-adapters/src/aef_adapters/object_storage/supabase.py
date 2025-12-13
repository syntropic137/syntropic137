"""Supabase Storage adapter for production artifact storage.

Provides S3-compatible object storage via Supabase's Storage API.
Used for production deployments where persistent, scalable storage is needed.

Requires:
    - AEF_STORAGE_SUPABASE_URL: Supabase project URL
    - AEF_STORAGE_SUPABASE_KEY: Supabase service role key
    - AEF_STORAGE_BUCKET_NAME: Storage bucket name (default: aef-artifacts)

Usage:
    from aef_adapters.object_storage import SupabaseStorage

    storage = SupabaseStorage(
        supabase_url="https://xxx.supabase.co",
        supabase_key="eyJ...",
        bucket_name="aef-artifacts"
    )
    await storage.upload("test.txt", b"hello")
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from aef_adapters.object_storage.protocol import (
    DownloadError,
    ListResult,
    ObjectNotFoundError,
    StorageConfigurationError,
    StorageObject,
    UploadError,
    UploadResult,
)

if TYPE_CHECKING:
    from aef_shared.settings.storage import StorageProvider

logger = logging.getLogger(__name__)


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
        from aef_shared.settings.storage import StorageProvider

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
        try:
            client = self._get_client()

            # Auto-detect content type if not provided
            if content_type is None:
                content_type, _ = mimetypes.guess_type(key)
                content_type = content_type or "application/octet-stream"

            # Prepare file options
            file_options: dict[str, str] = {"content-type": content_type}
            if metadata:
                # Supabase supports custom metadata via x-upsert-metadata header
                import json

                file_options["x-upsert-metadata"] = json.dumps(metadata)

            # Upload to Supabase Storage
            # Note: Supabase Storage uses upsert by default
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                partial(
                    client.storage.from_(self._bucket_name).upload,
                    path=key,
                    file=content,
                    file_options=file_options,
                ),
            )

            # Check for errors
            if hasattr(response, "error") and response.error:
                raise UploadError(f"Supabase upload failed: {response.error}", key=key)

            # Compute ETag
            etag = hashlib.md5(content, usedforsecurity=False).hexdigest()

            # Get public URL
            url_response = await loop.run_in_executor(
                None,
                partial(client.storage.from_(self._bucket_name).get_public_url, key),
            )

            return UploadResult(
                key=key,
                size_bytes=len(content),
                etag=etag,
                url=url_response if isinstance(url_response, str) else None,
            )

        except StorageConfigurationError:
            raise
        except Exception as e:
            logger.exception("Failed to upload to Supabase: %s", key)
            raise UploadError(f"Failed to upload {key}: {e}", key=key) from e

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
        try:
            client = self._get_client()

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                partial(client.storage.from_(self._bucket_name).download, key),
            )

            if response is None:
                raise ObjectNotFoundError(key)

            return response

        except ObjectNotFoundError:
            raise
        except StorageConfigurationError:
            raise
        except Exception as e:
            # Supabase returns 404 for not found
            error_msg = str(e).lower()
            if "not found" in error_msg or "404" in error_msg:
                raise ObjectNotFoundError(key) from e
            logger.exception("Failed to download from Supabase: %s", key)
            raise DownloadError(f"Failed to download {key}: {e}", key=key) from e

    async def delete(self, key: str) -> bool:
        """Delete an object from Supabase Storage.

        Args:
            key: Object key (path) to delete.

        Returns:
            True if object was deleted, False if it didn't exist.
        """
        try:
            client = self._get_client()

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                partial(client.storage.from_(self._bucket_name).remove, [key]),
            )

            # Supabase returns list of deleted files
            if response and isinstance(response, list):
                return len(response) > 0

            return False

        except Exception as e:
            logger.warning("Failed to delete from Supabase: %s - %s", key, e)
            return False

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
        try:
            client = self._get_client()

            # Supabase doesn't have a direct HEAD method, so we list with prefix
            # and filter for exact match
            parts = key.rsplit("/", 1)
            if len(parts) == 2:
                folder, filename = parts
            else:
                folder = ""
                filename = key

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                partial(client.storage.from_(self._bucket_name).list, folder),
            )

            if not response:
                return None

            # Find exact match
            for item in response:
                if item.get("name") == filename:
                    # Parse metadata
                    metadata = item.get("metadata", {})
                    size = metadata.get("size", 0)
                    content_type = metadata.get("mimetype")

                    # Parse last modified
                    last_modified_str = item.get("updated_at") or item.get("created_at")
                    if last_modified_str:
                        try:
                            last_modified = datetime.fromisoformat(
                                last_modified_str.replace("Z", "+00:00")
                            )
                        except (ValueError, TypeError):
                            last_modified = datetime.now(UTC)
                    else:
                        last_modified = datetime.now(UTC)

                    return StorageObject(
                        key=key,
                        size_bytes=size,
                        content_type=content_type,
                        etag=item.get("id"),
                        last_modified=last_modified,
                    )

            return None

        except Exception as e:
            logger.warning("Failed to get object info from Supabase: %s - %s", key, e)
            return None

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
        try:
            client = self._get_client()

            # Parse offset from continuation token
            offset = int(continuation_token) if continuation_token else 0

            # Supabase list returns files in a folder
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                partial(
                    client.storage.from_(self._bucket_name).list,
                    prefix,
                    {"limit": max_keys, "offset": offset},
                ),
            )

            if not response:
                return ListResult(objects=[], prefix=prefix if prefix else None)

            objects: list[StorageObject] = []
            for item in response:
                # Skip folders
                if item.get("id") is None:
                    continue

                name = item.get("name", "")
                full_key = f"{prefix}/{name}" if prefix else name

                metadata = item.get("metadata", {})
                size = metadata.get("size", 0)
                content_type = metadata.get("mimetype")

                # Parse last modified
                last_modified_str = item.get("updated_at") or item.get("created_at")
                if last_modified_str:
                    try:
                        last_modified = datetime.fromisoformat(
                            last_modified_str.replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        last_modified = datetime.now(UTC)
                else:
                    last_modified = datetime.now(UTC)

                objects.append(
                    StorageObject(
                        key=full_key,
                        size_bytes=size,
                        content_type=content_type,
                        etag=item.get("id"),
                        last_modified=last_modified,
                    )
                )

            # Check if truncated
            is_truncated = len(response) >= max_keys

            return ListResult(
                objects=objects,
                is_truncated=is_truncated,
                next_continuation_token=str(offset + max_keys) if is_truncated else None,
                prefix=prefix if prefix else None,
            )

        except Exception as e:
            logger.warning("Failed to list objects from Supabase: %s - %s", prefix, e)
            return ListResult(objects=[], prefix=prefix if prefix else None)

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
        if for_upload:
            raise NotImplementedError("Supabase presigned upload URLs not yet implemented")

        client = self._get_client()

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            partial(
                client.storage.from_(self._bucket_name).create_signed_url,
                key,
                expires_in,
            ),
        )

        if isinstance(response, dict) and "signedURL" in response:
            return response["signedURL"]

        # Fallback to public URL
        public_url = await loop.run_in_executor(
            None,
            partial(client.storage.from_(self._bucket_name).get_public_url, key),
        )
        return public_url
