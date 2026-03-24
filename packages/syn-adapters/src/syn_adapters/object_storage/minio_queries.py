"""Query helper functions for MinIO Storage adapter.

Extracted from minio_helpers.py to reduce per-file cognitive complexity.
Contains list operations.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_adapters.object_storage.protocol import (
    ListResult,
    StorageObject,
)

if TYPE_CHECKING:
    from minio import Minio

logger = logging.getLogger(__name__)


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
