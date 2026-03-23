"""Helper functions and mixin methods for Supabase Storage adapter.

Extracted from supabase.py to reduce per-file cognitive complexity.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from syn_adapters.object_storage.protocol import (
    ListResult,
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


def find_matching_object(
    response: list[dict[str, Any]], filename: str, key: str
) -> StorageObject | None:
    """Find an exact filename match in a Supabase list response."""
    for item in response:
        if item.get("name") == filename:
            return _storage_object_from_item(item, key)
    return None


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


async def get_object_info(
    get_client: Any,
    bucket_name: str,
    key: str,
) -> StorageObject | None:
    """Get object metadata without downloading content.

    Args:
        get_client: Callable returning the Supabase client.
        bucket_name: Storage bucket name.
        key: Object key (path) to get info for.

    Returns:
        StorageObject with metadata, or None if not found.
    """
    try:
        client = get_client()
        folder, filename = split_key(key)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            partial(client.storage.from_(bucket_name).list, folder),
        )

        if not response:
            return None

        return find_matching_object(response, filename, key)

    except Exception as e:
        logger.warning("Failed to get object info from Supabase: %s - %s", key, e)
        return None


async def list_objects(
    get_client: Any,
    bucket_name: str,
    prefix: str = "",
    *,
    max_keys: int = 1000,
    continuation_token: str | None = None,
) -> ListResult:
    """List objects matching a prefix in Supabase Storage.

    Args:
        get_client: Callable returning the Supabase client.
        bucket_name: Storage bucket name.
        prefix: Key prefix to filter by.
        max_keys: Maximum objects to return.
        continuation_token: Offset for pagination.

    Returns:
        ListResult with matching objects.
    """
    try:
        client = get_client()
        offset = int(continuation_token) if continuation_token else 0

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            partial(
                client.storage.from_(bucket_name).list,
                prefix,
                {"limit": max_keys, "offset": offset},
            ),
        )

        if not response:
            return ListResult(objects=[], prefix=prefix or None)

        objects = build_object_list(response, prefix)
        is_truncated = len(response) >= max_keys

        return ListResult(
            objects=objects,
            is_truncated=is_truncated,
            next_continuation_token=str(offset + max_keys) if is_truncated else None,
            prefix=prefix or None,
        )

    except Exception as e:
        logger.warning("Failed to list objects from Supabase: %s - %s", prefix, e)
        return ListResult(objects=[], prefix=prefix or None)


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
