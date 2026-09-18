"""Helper functions for MinIO Storage adapter.

Extracted from minio.py to reduce per-file cognitive complexity.
Contains metadata queries and sync upload/download helpers.
List operations are in minio_queries.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, NamedTuple

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
#: MinIO itself is read-after-write consistent, so in practice the first read
#: answers; the budget is here for S3-compatible backends that are not, and for
#: a bucket that is briefly serving a previous value at the key.
READABLE_TIMEOUT_SECONDS = 10.0

_POLL_INITIAL_SECONDS = 0.05
_POLL_MAX_SECONDS = 1.0

#: Enough of a digest to identify it in a log line without printing all 64.
_DIGEST_PREFIX = 12


class _Served(NamedTuple):
    """What a read of a key actually returned, summarised for comparison."""

    sha256: str
    size_bytes: int


async def _read_served(client: Minio, bucket_name: str, key: str) -> _Served | None:
    """Summarise the bytes the backend serves for `key`, or None if it serves none.

    This downloads. A `stat_object` would be cheaper and would answer a
    different question - see `await_readable_content` for why the cheaper
    question is the wrong one.
    """
    loop = asyncio.get_event_loop()
    try:
        payload = await loop.run_in_executor(
            None,
            partial(do_download, client, bucket_name, key),
        )
    except ObjectNotFoundError:
        return None
    except Exception as exc:
        raise UploadError(f"Failed to confirm upload of {key}: {exc}", key=key) from exc
    return _Served(sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))


def _describe(served: _Served | None) -> str:
    """How to name what a read saw, in the error a caller will have to act on."""
    if served is None:
        return "missing"
    return f"{served.size_bytes} bytes hashing sha256:{served.sha256[:_DIGEST_PREFIX]}"


async def await_readable_content(
    client: Minio,
    bucket_name: str,
    key: str,
    expected_sha256: str,
) -> None:
    """Block until a GET of `key` returns bytes hashing to `expected_sha256`.

    THE GUARANTEE IS READABILITY, NOT DURABILITY. Returning means a read issued
    now got exactly the bytes that were written. It says nothing about
    surviving the loss of a disk, a node or a site: that is a property of how
    the backend is deployed, not something any client call can establish.
    MinIO in distributed mode commits a write to erasure-coding write quorum
    before `put_object` returns, and a single-node single-drive MinIO - what
    `just dev` runs - has no redundancy at all and never will, whatever this
    function returns. So do not read "durable" into a successful upload, and do
    not write it in a docstring above one.

    Readability is nonetheless exactly the fact #700 needs. `put_object`
    returning means the backend accepted the write; `ArtifactCreatedEvent` then
    publishes a `storage_uri`, and a consumer that reacts to the event and
    fetches immediately was getting a 404 or a short object.

    IT READS THE OBJECT, AND THAT IS THE POINT. This check used to be a
    `stat_object` compared against the written length. A HEAD establishes that
    some metadata record of that size exists, which is a weaker claim than it
    looks and is passed by all three things that actually go wrong here: a HEAD
    answered from an index while the GET still 404s, a truncated object whose
    HEAD reports the full written length anyway, and a PREVIOUS object of the
    same size still being served at the key. One digest over the bytes a reader
    would receive rules out all three at once, so none of them needs a case of
    its own.

    The cost is one extra GET per upload. Artifacts are markdown deliverables,
    and the alternative is publishing a URI the platform cannot stand behind.

    Args:
        client: Minio client instance.
        bucket_name: Storage bucket name.
        key: Object key that was just written.
        expected_sha256: Hex SHA-256 of the bytes that were written.

    Raises:
        UploadError: If `key` does not serve those bytes within
            `READABLE_TIMEOUT_SECONDS`, or if the read fails outright.
    """
    loop = asyncio.get_event_loop()
    # Read at call time so the budget is one knob, tunable in one place.
    timeout_seconds = READABLE_TIMEOUT_SECONDS
    deadline = loop.time() + timeout_seconds
    delay = _POLL_INITIAL_SECONDS

    while True:
        served = await _read_served(client, bucket_name, key)
        if served is not None and served.sha256 == expected_sha256:
            return
        if loop.time() + delay > deadline:
            raise UploadError(
                f"Upload of {key} was accepted but a read still returns "
                f"{_describe(served)} after {timeout_seconds}s "
                f"(expected sha256:{expected_sha256[:_DIGEST_PREFIX]})",
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
