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

if TYPE_CHECKING:
    from syn_adapters.object_storage.protocol import StorageProtocol


def create_context_summary(
    phase_id: str | None,
    workflow_id: str | None,
    task: str,
    system_prompt: str | None,
    artifacts: list[ArtifactBundle],
    context_files: list[tuple[Path, bytes]],
) -> str:
    """Create a JSON summary of the phase context."""
    summary = {
        "phase_id": phase_id,
        "workflow_id": workflow_id,
        "task": task,
        "system_prompt": system_prompt,
        "artifacts": [
            {
                "bundle_id": b.bundle_id,
                "phase_id": b.phase_id,
                "title": b.title,
                "file_count": b.file_count,
                "files": [str(f.path) for f in b.files],
            }
            for b in artifacts
        ],
        "context_files": [str(p) for p, _ in context_files],
    }
    return json.dumps(summary, indent=2)


def build_context_files(
    artifacts: list[ArtifactBundle],
    context_files: list[tuple[Path, bytes]],
    phase_id: str | None,
    workflow_id: str | None,
    task: str,
    system_prompt: str | None,
) -> list[tuple[Path, bytes]]:
    """Convert all artifacts and context to injectable files.

    Returns list of (relative_path, content) tuples ready for
    workspace injection.
    """
    files: list[tuple[Path, bytes]] = []

    # Add artifact files under .context/artifacts/{bundle_id}/
    for bundle in artifacts:
        bundle_dir = Path(".context") / "artifacts" / bundle.bundle_id

        for artifact_file in bundle.files:
            context_path = bundle_dir / artifact_file.path
            files.append((context_path, artifact_file.content))

        # Add bundle manifest
        manifest_path = bundle_dir / "manifest.json"
        manifest_content = bundle.to_json().encode("utf-8")
        files.append((manifest_path, manifest_content))

    # Add any additional context files
    for path, content in context_files:
        context_path = Path(".context") / path
        files.append((context_path, content))

    # Add phase context summary
    summary = create_context_summary(
        phase_id, workflow_id, task, system_prompt, artifacts, context_files
    )
    summary_path = Path(".context") / "context.json"
    files.append((summary_path, summary.encode("utf-8")))

    return files


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

    if prefix:
        storage_prefix = prefix
    else:
        parts = []
        if workflow_id:
            parts.append(f"workflows/{workflow_id}")
        if session_id:
            parts.append(f"sessions/{session_id}")
        parts.append(f"bundles/{bundle_id}")
        storage_prefix = "/".join(parts) + "/"
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
        file_path = file_info["path"]
        file_key = storage_prefix + file_path
        content = await storage.download(file_key)
        meta_dict = file_info.get("metadata", {})
        metadata = ArtifactMetadata(
            workflow_id=meta_dict.get("workflow_id"),
            phase_id=meta_dict.get("phase_id"),
            session_id=meta_dict.get("session_id"),
            artifact_type=ArtifactType(meta_dict.get("artifact_type", "other")),
            title=meta_dict.get("title"),
            description=meta_dict.get("description"),
            is_primary=meta_dict.get("is_primary", False),
            derived_from=tuple(meta_dict.get("derived_from", [])),
            extra=meta_dict.get("extra", {}),
        )
        artifact_file = ArtifactFile(
            path=Path(file_path),
            content=content,
            content_hash=file_info.get("content_hash", ""),
            metadata=metadata,
            created_at=datetime.fromisoformat(file_info["created_at"]),
        )
        bundle.files.append(artifact_file)
    return bundle
