"""Artifact bundle storage operations.

Extracted from bundle.py to reduce module complexity.
"""

from __future__ import annotations

import json
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from syn_adapters.artifacts.bundle import (
    ArtifactBundle,
    ArtifactFile,
    ArtifactMetadata,
    ArtifactType,
)
from syn_adapters.artifacts.bundle_context import (
    build_context_files,
    create_context_summary,
)

if TYPE_CHECKING:
    from syn_adapters.object_storage.protocol import StorageProtocol

# Re-exported for backward compatibility
__all__ = [
    "build_context_files",
    "create_context_summary",
    "load_bundle_from_storage",
    "save_bundle_to_storage",
]


async def save_bundle_to_storage(
    bundle: ArtifactBundle,
    storage: StorageProtocol,
    *,
    prefix: str | None = None,
) -> list[str]:
    """Save all bundle files to object storage."""
    storage_prefix = prefix or bundle.get_storage_prefix()
    uploaded_keys: list[str] = []
    for artifact_file in bundle.files:
        key = storage_prefix + str(artifact_file.path).replace("\\", "/")
        content_type, _ = mimetypes.guess_type(str(artifact_file.path))
        await storage.upload(
            key,
            artifact_file.content,
            content_type=content_type,
            metadata={
                "artifact_type": artifact_file.metadata.artifact_type.value,
                "bundle_id": bundle.bundle_id,
                "phase_id": bundle.phase_id,
                "content_hash": artifact_file.content_hash,
            },
        )
        uploaded_keys.append(key)
    manifest_key = storage_prefix + "manifest.json"
    await storage.upload(
        manifest_key,
        bundle.to_json().encode("utf-8"),
        content_type="application/json",
    )
    uploaded_keys.append(manifest_key)
    return uploaded_keys


def _resolve_storage_prefix(
    bundle_id: str,
    prefix: str | None,
    workflow_id: str | None,
    session_id: str | None,
) -> str:
    """Build the storage prefix from explicit prefix or component IDs."""
    if prefix:
        return prefix
    parts: list[str] = []
    if workflow_id:
        parts.append(f"workflows/{workflow_id}")
    if session_id:
        parts.append(f"sessions/{session_id}")
    parts.append(f"bundles/{bundle_id}")
    return "/".join(parts) + "/"


def _parse_artifact_file(file_info: dict[str, object]) -> tuple[str, ArtifactMetadata]:
    """Parse a single file entry from the manifest into path and metadata."""
    meta_dict: dict[str, object] = file_info.get("metadata", {})  # type: ignore[assignment]
    metadata = ArtifactMetadata(
        workflow_id=meta_dict.get("workflow_id"),  # type: ignore[arg-type]
        phase_id=meta_dict.get("phase_id"),  # type: ignore[arg-type]
        session_id=meta_dict.get("session_id"),  # type: ignore[arg-type]
        artifact_type=ArtifactType(meta_dict.get("artifact_type", "other")),  # type: ignore[arg-type]
        title=meta_dict.get("title"),  # type: ignore[arg-type]
        description=meta_dict.get("description"),  # type: ignore[arg-type]
        is_primary=meta_dict.get("is_primary", False),  # type: ignore[arg-type]
        derived_from=tuple(meta_dict.get("derived_from", [])),  # type: ignore[arg-type]
        extra=meta_dict.get("extra", {}),  # type: ignore[arg-type]
    )
    return str(file_info["path"]), metadata


async def load_bundle_from_storage(
    storage: StorageProtocol,
    bundle_id: str,
    *,
    prefix: str | None = None,
    workflow_id: str | None = None,
    session_id: str | None = None,
) -> ArtifactBundle:
    """Load a bundle from object storage."""
    from syn_adapters.object_storage.protocol import DownloadError, ObjectNotFoundError

    storage_prefix = _resolve_storage_prefix(bundle_id, prefix, workflow_id, session_id)
    manifest_key = storage_prefix + "manifest.json"
    try:
        manifest_bytes = await storage.download(manifest_key)
    except ObjectNotFoundError:
        raise
    except (DownloadError, OSError) as e:
        raise ObjectNotFoundError(manifest_key) from e
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    bundle = ArtifactBundle(
        bundle_id=manifest["bundle_id"],
        phase_id=manifest["phase_id"],
        session_id=manifest.get("session_id"),
        workflow_id=manifest.get("workflow_id"),
        title=manifest.get("title"),
        description=manifest.get("description"),
        is_primary=manifest.get("is_primary", True),
        created_at=datetime.fromisoformat(manifest["created_at"]),
    )
    for file_info in manifest.get("files", []):
        file_path, metadata = _parse_artifact_file(file_info)
        file_key = storage_prefix + file_path
        content = await storage.download(file_key)
        artifact_file = ArtifactFile(
            path=Path(file_path),
            content=content,
            content_hash=file_info.get("content_hash", ""),
            metadata=metadata,
            created_at=datetime.fromisoformat(file_info["created_at"]),
        )
        bundle.files.append(artifact_file)
    return bundle
