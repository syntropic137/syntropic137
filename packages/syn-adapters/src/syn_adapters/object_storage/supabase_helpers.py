"""Helper functions and mixin methods for Supabase Storage adapter.

Extracted from supabase.py to reduce per-file cognitive complexity.
Contains sync helper utilities and presigned-URL support.
Query operations (list, get_object_info) are in supabase_queries.py.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from syn_adapters.object_storage.protocol import (
    DownloadError,
    ObjectNotFoundError,
    StorageObject,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _parse_last_modified(item: dict[str, Any]) -> datetime:
    """Parse last-modified timestamp from a Supabase list item."""
    last_modified_str = item.get("updated_at") or item.get("created_at")
    if not last_modified_str:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(last_modified_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now(UTC)


def _storage_object_from_item(item: dict[str, Any], key: str) -> StorageObject:
    """Build a StorageObject from a Supabase list item."""
    metadata = item.get("metadata", {})
    return StorageObject(
        key=key,
        size_bytes=metadata.get("size", 0),
        content_type=metadata.get("mimetype"),
        etag=item.get("id"),
        last_modified=_parse_last_modified(item),
    )


def split_key(key: str) -> tuple[str, str]:
    """Split an object key into (folder, filename)."""
    parts = key.rsplit("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", key


def build_object_list(
    response: list[dict[str, Any]], prefix: str
) -> list[StorageObject]:
    """Convert a Supabase list response into StorageObject instances, skipping folders."""
    objects: list[StorageObject] = []
    for item in response:
        if item.get("id") is None:
            continue
        name = item.get("name", "")
        full_key = f"{prefix}/{name}" if prefix else name
        objects.append(_storage_object_from_item(item, full_key))
    return objects


def do_download(
    client: Any,
    bucket_name: str,
    key: str,
) -> bytes:
    """Synchronous download body for Supabase Storage (run in executor).

    Converts 404/not-found errors to ObjectNotFoundError and wraps
    other failures in DownloadError so the async caller needs no try/except.

    Args:
        client: Supabase client instance.
        bucket_name: Storage bucket name.
        key: Object key (path) to download.

    Returns:
        Raw bytes of the object content.

    Raises:
        ObjectNotFoundError: If object doesn't exist.
        DownloadError: If download fails for other reasons.
    """
    try:
        response = client.storage.from_(bucket_name).download(key)
        if response is None:
            raise ObjectNotFoundError(key)
        return response  # type: ignore[return-value]
    except ObjectNotFoundError:
        raise
    except Exception as exc:
        error_msg = str(exc).lower()
        if "not found" in error_msg or "404" in error_msg:
            raise ObjectNotFoundError(key) from exc
        logger.exception("Failed to download from Supabase: %s", key)
        raise DownloadError(f"Failed to download {key}: {exc}", key=key) from exc


def do_delete(
    client: Any,
    bucket_name: str,
    key: str,
) -> bool:
    """Synchronous delete body for Supabase Storage (run in executor).

    Args:
        client: Supabase client instance.
        bucket_name: Storage bucket name.
        key: Object key (path) to delete.

    Returns:
        True if object was deleted, False if it didn't exist.
    """
    try:
        response = client.storage.from_(bucket_name).remove([key])
        if response and isinstance(response, list):
            return len(response) > 0
        return False
    except Exception as e:
        logger.warning("Failed to delete from Supabase: %s - %s", key, e)
        return False


async def get_presigned_url(
    get_client: Any,
    bucket_name: str,
    key: str,
    *,
    expires_in: int = 3600,
    for_upload: bool = False,
) -> str:
    """Get a presigned URL for direct access.

    Args:
        get_client: Callable returning the Supabase client.
        bucket_name: Storage bucket name.
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

    client = get_client()

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        partial(
            client.storage.from_(bucket_name).create_signed_url,
            key,
            expires_in,
        ),
    )

    if isinstance(response, dict) and "signedURL" in response:
        return response["signedURL"]

    # Fallback to public URL
    public_url = await loop.run_in_executor(
        None,
        partial(client.storage.from_(bucket_name).get_public_url, key),
    )
    return public_url
