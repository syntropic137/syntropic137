"""Object storage adapters for artifact storage.

This module provides storage adapters for storing and retrieving agent artifacts.
Supports local filesystem (development) and Supabase Storage (production).

See ADR-012: Artifact Storage

Environment-based selection via AEF_STORAGE_* variables:
- **LOCAL** (default): Uses filesystem at AEF_STORAGE_LOCAL_PATH
  Fast, simple, no external dependencies. For development.

- **SUPABASE**: Uses Supabase Storage (S3-compatible)
  Requires AEF_STORAGE_SUPABASE_URL and AEF_STORAGE_SUPABASE_KEY.
  For production.

Usage:
    from aef_adapters.object_storage import get_storage

    # Get storage adapter (auto-selects based on environment)
    storage = await get_storage()

    # Upload artifact
    result = await storage.upload(
        "workflows/123/artifacts/report.md",
        report_content.encode()
    )

    # Download artifact
    content = await storage.download("workflows/123/artifacts/report.md")

    # List artifacts
    artifacts = await storage.list_objects("workflows/123/artifacts/")
"""

from aef_adapters.object_storage.factory import get_storage, reset_storage
from aef_adapters.object_storage.local import LocalStorage
from aef_adapters.object_storage.protocol import (
    DownloadError,
    ListResult,
    ObjectNotFoundError,
    StorageConfigurationError,
    StorageError,
    StorageObject,
    StorageProtocol,
    UploadError,
    UploadResult,
)
from aef_adapters.object_storage.supabase import SupabaseStorage

__all__ = [
    "DownloadError",
    "ListResult",
    "LocalStorage",
    "ObjectNotFoundError",
    "StorageConfigurationError",
    "StorageError",
    "StorageObject",
    "StorageProtocol",
    "SupabaseStorage",
    "UploadError",
    "UploadResult",
    "get_storage",
    "reset_storage",
]
