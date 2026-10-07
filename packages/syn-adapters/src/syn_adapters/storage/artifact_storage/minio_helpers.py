"""MinIO artifact storage helper functions.

Extracted from minio.py to reduce module complexity.
"""

from __future__ import annotations

from typing import Any


def build_artifact_key(
    artifact_id: str,
    workflow_id: str | None = None,
    execution_id: str | None = None,
    *,
    prefix: str = "artifacts",
) -> str:
    """Where an artifact's content lives: ``{prefix}/{workflow_id}/{execution_id}/{artifact_id}.md``.

    The one definition of the artifact keyspace, shared by the MinIO adapter
    and its in-memory stand-in so the two cannot disagree on where an upload
    landed (#990: the fake keyed by id alone and hid every 404).
    """
    parts = [prefix]
    if workflow_id:
        parts.append(workflow_id)
    if execution_id:
        parts.append(execution_id)
    parts.append(f"{artifact_id}.md")
    return "/".join(parts)


def parse_s3_key(uri: str) -> str | None:
    """Extract the object key from an s3://bucket/key URI, or return None."""
    if not uri.startswith("s3://"):
        return None
    parts = uri[5:].split("/", 1)
    return parts[1] if len(parts) == 2 else None


def build_s3_metadata(
    artifact_id: str,
    content_hash: str,
    phase_id: str | None,
    execution_id: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, str]:
    """Assemble S3 metadata dict from artifact fields."""
    s3_metadata: dict[str, str] = {
        "artifact_id": artifact_id,
        "content_hash": content_hash,
    }
    if phase_id:
        s3_metadata["phase_id"] = phase_id
    if execution_id:
        s3_metadata["execution_id"] = execution_id
    if metadata:
        for k, v in metadata.items():
            s3_metadata[k] = str(v)
    return s3_metadata
