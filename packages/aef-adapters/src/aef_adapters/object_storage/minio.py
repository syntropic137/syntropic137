"""MinIO Storage adapter for self-hosted S3-compatible storage.

Provides object storage via MinIO's S3-compatible API. Ideal for:
- Self-hosted deployments
- Air-gapped environments
- Development with S3 API (default for `just dev`)

Requires:
    - AEF_STORAGE_MINIO_ENDPOINT: MinIO server endpoint (host:port)
    - AEF_STORAGE_MINIO_ACCESS_KEY: Access key
    - AEF_STORAGE_MINIO_SECRET_KEY: Secret key
    - AEF_STORAGE_BUCKET_NAME: Bucket name (default: aef-artifacts)

Usage:
    from aef_adapters.object_storage import MinioStorage

    storage = MinioStorage(
        endpoint="localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket_name="aef-artifacts",
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
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

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
    from minio import Minio

    from aef_shared.settings.storage import StorageProvider

logger = logging.getLogger(__name__)


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
        from aef_shared.settings.storage import StorageProvider

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
        try:
            await self._ensure_bucket()
            client = self._get_client()

            # Auto-detect content type if not provided
            if content_type is None:
                content_type, _ = mimetypes.guess_type(key)
                content_type = content_type or "application/octet-stream"

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                partial(
                    client.put_object,
                    self._bucket_name,
                    key,
                    io.BytesIO(content),
                    len(content),
                    content_type=content_type,
                    # Cast metadata to minio's expected type (dict values are just strings)
                    metadata=metadata if metadata else None,  # type: ignore[arg-type]
                ),
            )

            # Compute ETag
            etag = hashlib.md5(content, usedforsecurity=False).hexdigest()

            return UploadResult(
                key=key,
                size_bytes=len(content),
                etag=result.etag if hasattr(result, "etag") else etag,
                url=None,  # MinIO doesn't provide public URLs by default
            )

        except StorageConfigurationError:
            raise
        except Exception as e:
            logger.exception("Failed to upload to MinIO: %s", key)
            raise UploadError(f"Failed to upload {key}: {e}", key=key) from e

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
        try:
            client = self._get_client()

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                partial(client.get_object, self._bucket_name, key),
            )

            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        except StorageConfigurationError:
            raise
        except Exception as e:
            error_msg = str(e).lower()
            if "nosuchkey" in error_msg or "not found" in error_msg:
                raise ObjectNotFoundError(key) from e
            logger.exception("Failed to download from MinIO: %s", key)
            raise DownloadError(f"Failed to download {key}: {e}", key=key) from e

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
        try:
            client = self._get_client()

            loop = asyncio.get_event_loop()
            stat = await loop.run_in_executor(
                None,
                partial(client.stat_object, self._bucket_name, key),
            )

            return StorageObject(
                key=key,
                size_bytes=stat.size or 0,
                content_type=stat.content_type,
                etag=stat.etag,
                last_modified=stat.last_modified or datetime.now(UTC),
            )

        except Exception as e:
            error_msg = str(e).lower()
            if "nosuchkey" in error_msg or "not found" in error_msg:
                return None
            logger.warning("Failed to get object info from MinIO: %s - %s", key, e)
            return None

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
        try:
            client = self._get_client()

            loop = asyncio.get_event_loop()

            def list_objects_sync() -> list[StorageObject]:
                objects: list[StorageObject] = []
                for obj in client.list_objects(self._bucket_name, prefix=prefix):
                    if len(objects) >= max_keys:
                        break
                    objects.append(
                        StorageObject(
                            key=obj.object_name or "",
                            size_bytes=obj.size or 0,
                            content_type=None,
                            etag=obj.etag,
                            last_modified=obj.last_modified or datetime.now(UTC),
                        )
                    )
                return objects

            objects = await loop.run_in_executor(None, list_objects_sync)

            return ListResult(
                objects=objects,
                is_truncated=len(objects) >= max_keys,
                prefix=prefix if prefix else None,
            )

        except Exception as e:
            logger.warning("Failed to list objects from MinIO: %s - %s", prefix, e)
            return ListResult(objects=[], prefix=prefix if prefix else None)

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
        try:
            from datetime import timedelta

            client = self._get_client()

            loop = asyncio.get_event_loop()
            url = await loop.run_in_executor(
                None,
                partial(
                    client.presigned_get_object,
                    self._bucket_name,
                    key,
                    expires=timedelta(seconds=expires_in),
                ),
            )
            return url

        except Exception as e:
            logger.warning("Failed to generate presigned URL: %s - %s", key, e)
            # Fallback to a non-presigned path
            protocol = "https" if self._secure else "http"
            return f"{protocol}://{self._endpoint}/{self._bucket_name}/{key}"
