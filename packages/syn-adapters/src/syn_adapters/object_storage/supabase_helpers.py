"""Helper functions and mixin methods for Supabase Storage adapter.

Extracted from supabase.py to reduce per-file cognitive complexity.
Contains sync helper utilities and presigned-URL support.
Query operations (list, get_object_info) are in supabase_queries.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from syn_adapters.object_storage.protocol import (
    DownloadError,
    ObjectNotFoundError,
    StorageObject,
    UploadError,
    UploadResult,
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


def do_upload(
    client: Any,
    bucket_name: str,
    key: str,
    content: bytes,
    content_type: str | None,
    metadata: dict[str, str] | None,
) -> UploadResult:
    """Synchronous upload body for Supabase Storage (run in executor).

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


def do_download(
    client: Any,
    bucket_name: str,
    key: str,
) -> bytes:
    """Synchronous download body for Supabase Storage (run in executor).

    Raises ObjectNotFoundError for 404/not-found conditions so the
    async caller does not need to inspect error messages.

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
    except Exception as exc:
        error_msg = str(exc).lower()
        if "not found" in error_msg or "404" in error_msg:
            raise ObjectNotFoundError(key) from exc
        raise

    if response is None:
        raise ObjectNotFoundError(key)

    return response  # type: ignore[return-value]


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
    response = client.storage.from_(bucket_name).remove([key])

    if response and isinstance(response, list):
        return len(response) > 0

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
