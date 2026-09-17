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
    UploadError,
)

if TYPE_CHECKING:
    from minio import Minio

logger = logging.getLogger(__name__)

#: How long a write may take to become readable before we call the upload failed.
#: MinIO itself is read-after-write consistent, so in practice the first stat
#: answers; the budget is here for S3-compatible backends that are not, and for
#: a bucket that is briefly serving a stale index.
READABLE_TIMEOUT_SECONDS = 10.0

_POLL_INITIAL_SECONDS = 0.05
_POLL_MAX_SECONDS = 1.0


def _is_missing(exc: Exception) -> bool:
    """Whether a stat failure means "not there yet" rather than "broken"."""
    error_msg = str(exc).lower()
    return "nosuchkey" in error_msg or "not found" in error_msg


async def _readable_size(client: Minio, bucket_name: str, key: str) -> int | None:
    """Size the backend will currently serve for `key`, or None if it has none."""
    loop = asyncio.get_event_loop()
    try:
        stat = await loop.run_in_executor(
            None,
            partial(client.stat_object, bucket_name, key),
        )
    except Exception as exc:
        if _is_missing(exc):
            return None
        raise UploadError(f"Failed to confirm upload of {key}: {exc}", key=key) from exc
    return stat.size


async def await_object_readable(
    client: Minio,
    bucket_name: str,
    key: str,
    expected_size: int,
) -> None:
    """Block until `key` serves `expected_size` bytes to a reader.

    `put_object` returning means the backend accepted the write, not that the
    next reader can see it. Anything that publishes a pointer to the object
    needs the stronger fact - `ArtifactCreatedEvent` carries a `storage_uri`,
    and a consumer that reacts to it and fetches immediately was getting a 404
    or a short object (#700). Confirming here is what lets every caller treat a
    returned upload as durable without knowing how that was established.

    Size is checked, not just existence, because a short read is the same
    failure as a missing one to the consumer and is far harder to spot.

    Raises:
        UploadError: If `key` is not readable at `expected_size` within
            `READABLE_TIMEOUT_SECONDS`, or if the backend fails the check
            outright.
    """
    loop = asyncio.get_event_loop()
    # Read at call time so the budget is one knob, tunable in one place.
    timeout_seconds = READABLE_TIMEOUT_SECONDS
    deadline = loop.time() + timeout_seconds
    delay = _POLL_INITIAL_SECONDS

    while True:
        size = await _readable_size(client, bucket_name, key)
        if size == expected_size:
            return
        if loop.time() + delay > deadline:
            seen = "missing" if size is None else f"{size} bytes"
            raise UploadError(
                f"Upload of {key} was accepted but is still {seen} after "
                f"{timeout_seconds}s (expected {expected_size} bytes)",
                key=key,
            )
        await asyncio.sleep(delay)
        delay = min(delay * 2, _POLL_MAX_SECONDS)


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
