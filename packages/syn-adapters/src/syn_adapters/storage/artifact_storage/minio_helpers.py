"""MinIO artifact storage helper functions.

Extracted from minio.py to reduce module complexity.
"""

from __future__ import annotations

from typing import Any


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
