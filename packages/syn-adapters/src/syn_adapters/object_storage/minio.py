"""MinIO Storage adapter for self-hosted S3-compatible storage.

Provides object storage via MinIO's S3-compatible API. Ideal for:
- Self-hosted deployments
- Air-gapped environments
- Development with S3 API (default for `just dev`)

Requires:
    - SYN_STORAGE_MINIO_ENDPOINT: MinIO server endpoint (host:port)
    - SYN_STORAGE_MINIO_ACCESS_KEY: Access key
    - SYN_STORAGE_MINIO_SECRET_KEY: Secret key
    - SYN_STORAGE_BUCKET_NAME: Bucket name (default: syn-artifacts)

Usage:
    from syn_adapters.object_storage import MinioStorage

    storage = MinioStorage(
        endpoint="localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket_name="syn-artifacts",
        secure=False
    )
    await storage.upload("test.txt", b"hello")
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import mimetypes
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from syn_adapters.object_storage.minio_helpers import (
    do_download as _do_download,
)
from syn_adapters.object_storage.minio_helpers import (
    get_object_info as _get_object_info,
)
from syn_adapters.object_storage.minio_helpers import (
    get_presigned_url as _get_presigned_url,
)
from syn_adapters.object_storage.minio_queries import (
    list_objects as _list_objects,
)
from syn_adapters.object_storage.protocol import (
    ListResult,
    StorageConfigurationError,
    StorageObject,
    UploadError,
    UploadResult,
)

if TYPE_CHECKING:
    from minio import Minio

    from syn_shared.settings.storage import StorageProvider

logger = logging.getLogger(__name__)


def _resolve_content_type(key: str, content_type: str | None) -> str:
    """Resolve content type, auto-detecting from key if not provided."""
    if content_type is not None:
        return content_type
    guessed, _ = mimetypes.guess_type(key)
    return guessed or "application/octet-stream"


def _do_upload(
    client: Minio,
    bucket_name: str,
    key: str,
    content: bytes,
    content_type: str | None,
    metadata: dict[str, str] | None,
) -> UploadResult:
    """Synchronous upload body for MinIO (run in executor).

    Handles content-type detection, put_object, and ETag computation.
    Raises UploadError on failure so the async caller needs no try/except.

    Args:
        client: Minio client instance.
        bucket_name: Storage bucket name.
        key: Object key (path) within the bucket.
        content: Raw bytes to store.
        content_type: MIME type. Auto-detected if not provided.
        metadata: Custom metadata.

    Returns:
        UploadResult with key, size, and ETag.

    Raises:
        UploadError: If upload fails.
    """
    try:
        resolved_type = _resolve_content_type(key, content_type)

        result = client.put_object(
            bucket_name,
            key,
            io.BytesIO(content),
            len(content),
            content_type=resolved_type,
            metadata=cast("dict[str, Any]", metadata) if metadata else None,
        )

        etag = hashlib.md5(content, usedforsecurity=False).hexdigest()

        return UploadResult(
            key=key,
            size_bytes=len(content),
            etag=result.etag if hasattr(result, "etag") else etag,
            url=None,
        )
    except UploadError:
        raise
    except Exception as e:
        logger.exception("Failed to upload to MinIO: %s", key)
        raise UploadError(f"Failed to upload {key}: {e}", key=key) from e


class MinioStorage:
    """MinIO Storage adapter.

    Uses MinIO's S3-compatible API for object storage operations.
    MinIO provides:
    - S3 API compatibility
    - Self-hosted deployment
    - High performance
    - Kubernetes native

    Thread-safe - operations are wrapped in asyncio executors.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        *,
        secure: bool = True,
    ) -> None:
        """Initialize MinIO storage.

        Args:
            endpoint: MinIO server endpoint (host:port).
            access_key: MinIO access key.
            secret_key: MinIO secret key.
            bucket_name: Storage bucket name.
            secure: Use HTTPS. Default True.

        Raises:
            StorageConfigurationError: If minio package not installed.
        """
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket_name = bucket_name
        self._secure = secure
        self._client: Minio | None = None

    def _get_client(self) -> Minio:
        """Get or create MinIO client.

        Returns:
            MinIO client instance.

        Raises:
            StorageConfigurationError: If minio package not installed.
        """
        if self._client is not None:
            return self._client

        try:
            from minio import Minio

            self._client = Minio(
                self._endpoint,
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=self._secure,
            )
            return self._client
        except ImportError as e:
            raise StorageConfigurationError(
                "MinIO package not installed. Install with: pip install minio"
            ) from e

    @property
    def provider(self) -> StorageProvider:
        """Get the storage provider type."""
        from syn_shared.settings.storage import StorageProvider

        return StorageProvider.MINIO

    @property
    def bucket_name(self) -> str:
        """Get the bucket name."""
        return self._bucket_name

    async def _ensure_bucket(self) -> None:
        """Ensure the bucket exists, create if not."""
        client = self._get_client()
        loop = asyncio.get_event_loop()

        exists = await loop.run_in_executor(
            None,
            partial(client.bucket_exists, self._bucket_name),
        )

        if not exists:
            await loop.run_in_executor(
                None,
                partial(client.make_bucket, self._bucket_name),
            )
            logger.info("Created MinIO bucket: %s", self._bucket_name)

    async def upload(
        self,
        key: str,
        content: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResult:
        """Upload content to MinIO.

        Args:
            key: Object key (path) within the bucket.
            content: Raw bytes to store.
            content_type: MIME type. Auto-detected if not provided.
            metadata: Custom metadata.

        Returns:
            UploadResult with key, size, and ETag.

        Raises:
            UploadError: If upload fails.
        """
        await self._ensure_bucket()
        client = self._get_client()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            partial(_do_upload, client, self._bucket_name, key, content, content_type, metadata),
        )

    async def download(self, key: str) -> bytes:
        """Download content from MinIO.

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
        """Delete an object from MinIO.

        Args:
            key: Object key (path) to delete.

        Returns:
            True if object was deleted, False if it didn't exist.
        """
        try:
            client = self._get_client()

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                partial(client.remove_object, self._bucket_name, key),
            )
            return True

        except Exception as e:
            logger.warning("Failed to delete from MinIO: %s - %s", key, e)
            return False

    async def exists(self, key: str) -> bool:
        """Check if an object exists in MinIO.

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
        continuation_token: str | None = None,  # noqa: ARG002 - not used for MinIO
    ) -> ListResult:
        """List objects matching a prefix in MinIO.

        Args:
            prefix: Key prefix to filter by.
            max_keys: Maximum objects to return.
            continuation_token: Not used for MinIO (uses iterator).

        Returns:
            ListResult with matching objects.
        """
        return await _list_objects(
            self._get_client,
            self._bucket_name,
            prefix,
            max_keys=max_keys,
        )

    async def get_presigned_url(
        self,
        key: str,
        *,
        expires_in: int = 3600,
        for_upload: bool = False,  # noqa: ARG002 - not yet implemented
    ) -> str:
        """Get a presigned URL for direct access.

        Args:
            key: Object key (path).
            expires_in: Seconds until URL expires.
            for_upload: If True, generate upload URL (not yet supported).

        Returns:
            Presigned URL string.
        """
        return await _get_presigned_url(
            self._get_client,
            self._bucket_name,
            key,
            expires_in=expires_in,
            secure=self._secure,
            endpoint=self._endpoint,
        )
