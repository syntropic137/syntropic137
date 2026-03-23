"""Helper functions for Local filesystem storage adapter.

Extracted from local.py to reduce per-file cognitive complexity.
"""

from __future__ import annotations

import asyncio
import mimetypes
from datetime import UTC, datetime
from pathlib import Path

from syn_adapters.object_storage.protocol import (
    ListResult,
    StorageObject,
)


def resolve_search_params(base_path: Path, prefix: str, resolve_path: object) -> tuple[Path, str]:
    """Resolve the search path and glob pattern from a prefix.

    Args:
        base_path: Base directory for local storage.
        prefix: Key prefix to filter by.
        resolve_path: Callable to resolve a key to a full file path.

    Returns:
        Tuple of (search_path, glob_pattern).
    """
    if not prefix:
        return base_path, "**/*"

    search_path: Path = resolve_path(prefix)  # type: ignore[operator]
    if prefix.endswith("/"):
        return search_path, "*"

    return search_path.parent, prefix.split("/")[-1] + "*"


def file_to_storage_object(base_path: Path, file_path: Path) -> StorageObject:
    """Convert a filesystem path to a StorageObject.

    Args:
        base_path: Base directory for local storage.
        file_path: Absolute path to the file.

    Returns:
        StorageObject with metadata from the filesystem.
    """
    relative_path = file_path.relative_to(base_path)
    key = str(relative_path).replace("\\", "/")
    stat = file_path.stat()
    content_type, _ = mimetypes.guess_type(str(file_path))

    return StorageObject(
        key=key,
        size_bytes=stat.st_size,
        content_type=content_type,
        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


def collect_files(
    base_path: Path, search_path: Path, pattern: str, max_keys: int
) -> list[StorageObject]:
    """Collect matching files from the filesystem (runs in executor).

    Args:
        base_path: Base directory for local storage.
        search_path: Directory to search in.
        pattern: Glob pattern to match.
        max_keys: Maximum files to return.

    Returns:
        List of StorageObject instances for matching files.
    """
    if not search_path.exists():
        return []

    result: list[StorageObject] = []
    for file_path in search_path.rglob(pattern):
        if len(result) >= max_keys:
            break
        if file_path.is_file():
            result.append(file_to_storage_object(base_path, file_path))
    return result


async def get_object_info(
    resolve_path: object,
    key: str,
) -> StorageObject | None:
    """Get file metadata without reading content.

    Args:
        resolve_path: Callable to resolve a key to a full file path.
        key: Object key (relative path).

    Returns:
        StorageObject with metadata, or None if not found.
    """
    try:
        file_path: Path = resolve_path(key)  # type: ignore[operator]

        if not file_path.exists() or not file_path.is_file():
            return None

        stat = file_path.stat()
        content_type, _ = mimetypes.guess_type(str(file_path))

        return StorageObject(
            key=key,
            size_bytes=stat.st_size,
            content_type=content_type,
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )
    except ValueError:
        return None
    except Exception:
        return None


async def list_objects(
    base_path: Path,
    resolve_path: object,
    prefix: str = "",
    *,
    max_keys: int = 1000,
) -> ListResult:
    """List files matching a prefix.

    Args:
        base_path: Base directory for local storage.
        resolve_path: Callable to resolve a key to a full file path.
        prefix: Key prefix to filter by.
        max_keys: Maximum files to return.

    Returns:
        ListResult with matching files.
    """
    prefix_or_none = prefix if prefix else None
    try:
        search_path, pattern = resolve_search_params(base_path, prefix, resolve_path)
        objects = await asyncio.get_event_loop().run_in_executor(
            None, collect_files, base_path, search_path, pattern, max_keys
        )
        return ListResult(
            objects=objects,
            is_truncated=len(objects) >= max_keys,
            prefix=prefix_or_none,
        )
    except ValueError:
        return ListResult(objects=[], prefix=prefix_or_none)
    except Exception:
        return ListResult(objects=[], prefix=prefix_or_none)


async def get_presigned_url(
    resolve_path: object,
    key: str,
) -> str:
    """Get a file:// URL for local access.

    Note: This returns a file:// URL, not a presigned URL.
    Presigned URLs are not applicable to local filesystem.

    Args:
        resolve_path: Callable to resolve a key to a full file path.
        key: Object key (relative path).

    Returns:
        file:// URL to the local file.
    """
    file_path: Path = resolve_path(key)  # type: ignore[operator]
    return f"file://{file_path}"
