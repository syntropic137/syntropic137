"""Helper functions for MinIO Storage adapter.

Extracted from minio.py to reduce per-file cognitive complexity.
Contains metadata queries and sync upload/download helpers.
List operations are in minio_queries.py.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

from syn_adapters.object_storage.protocol import (
    DownloadError,
    ObjectNotFoundError,
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


def do_download(
    client: Minio,
    bucket_name: str,
    key: str,
) -> bytes:
    """Synchronous download body for MinIO (run in executor).

    Converts nosuchkey/not-found errors to ObjectNotFoundError and wraps
    other failures in DownloadError so the async caller needs no try/except.

    Args:
        client: Minio client instance.
        bucket_name: Storage bucket name.
        key: Object key (path) to download.

    Returns:
        Raw bytes of the object content.

    Raises:
        ObjectNotFoundError: If object doesn't exist.
        DownloadError: If download fails for other reasons.
    """
    try:
        response = client.get_object(bucket_name, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    except (ObjectNotFoundError, DownloadError):
        raise
    except Exception as exc:
        error_msg = str(exc).lower()
        if "nosuchkey" in error_msg or "not found" in error_msg:
            raise ObjectNotFoundError(key) from exc
        logger.exception("Failed to download from MinIO: %s", key)
        raise DownloadError(f"Failed to download {key}: {exc}", key=key) from exc


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
