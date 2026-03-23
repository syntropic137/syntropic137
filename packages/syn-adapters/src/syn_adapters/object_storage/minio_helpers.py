"""Helper functions for MinIO Storage adapter.

Extracted from minio.py to reduce per-file cognitive complexity.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

from syn_adapters.object_storage.protocol import (
    ListResult,
    StorageObject,
)

if TYPE_CHECKING:
    from minio import Minio

logger = logging.getLogger(__name__)


async def get_object_info(
    get_client: object,
    bucket_name: str,
    key: str,
) -> StorageObject | None:
    """Get object metadata without downloading content.

    Args:
        get_client: Callable returning the Minio client.
        bucket_name: Storage bucket name.
        key: Object key (path) to get info for.

    Returns:
        StorageObject with metadata, or None if not found.
    """
    try:
        client: Minio = get_client()  # type: ignore[operator]

        loop = asyncio.get_event_loop()
        stat = await loop.run_in_executor(
            None,
            partial(client.stat_object, bucket_name, key),
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
    get_client: object,
    bucket_name: str,
    prefix: str = "",
    *,
    max_keys: int = 1000,
) -> ListResult:
    """List objects matching a prefix in MinIO.

    Args:
        get_client: Callable returning the Minio client.
        bucket_name: Storage bucket name.
        prefix: Key prefix to filter by.
        max_keys: Maximum objects to return.

    Returns:
        ListResult with matching objects.
    """
    try:
        client: Minio = get_client()  # type: ignore[operator]

        loop = asyncio.get_event_loop()

        def list_objects_sync() -> list[StorageObject]:
            objects: list[StorageObject] = []
            for obj in client.list_objects(bucket_name, prefix=prefix):
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
    get_client: object,
    bucket_name: str,
    key: str,
    *,
    expires_in: int = 3600,
    secure: bool = True,
    endpoint: str = "",
) -> str:
    """Get a presigned URL for direct access.

    Args:
        get_client: Callable returning the Minio client.
        bucket_name: Storage bucket name.
        key: Object key (path).
        expires_in: Seconds until URL expires.
        secure: Whether the endpoint uses HTTPS.
        endpoint: MinIO server endpoint (for fallback URL).

    Returns:
        Presigned URL string.
    """
    try:
        from datetime import timedelta

        client: Minio = get_client()  # type: ignore[operator]

        loop = asyncio.get_event_loop()
        url = await loop.run_in_executor(
            None,
            partial(
                client.presigned_get_object,
                bucket_name,
                key,
                expires=timedelta(seconds=expires_in),
            ),
        )
        return url

    except Exception as e:
        logger.warning("Failed to generate presigned URL: %s - %s", key, e)
        # Fallback to a non-presigned path
        protocol = "https" if secure else "http"
        return f"{protocol}://{endpoint}/{bucket_name}/{key}"
