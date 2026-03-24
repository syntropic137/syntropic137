"""Query helper functions for Supabase Storage adapter.

Extracted from supabase_helpers.py to reduce per-file cognitive complexity.
Contains list and metadata query operations.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any

from syn_adapters.object_storage.protocol import (
    ListResult,
    StorageObject,
)
from syn_adapters.object_storage.supabase_helpers import (
    build_object_list,
    find_matching_object,
    split_key,
)

logger = logging.getLogger(__name__)


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
