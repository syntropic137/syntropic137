"""UploadArtifact command - request to upload an artifact bundle to storage."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UploadArtifactCommand:
    """Command to upload an artifact bundle to object storage.

    This command is typically issued after a phase completes and
    artifacts have been collected from the workspace.
    """

    # Bundle identity
    bundle_id: str
    """Unique identifier for the artifact bundle."""

    # Context
    workflow_id: str | None = None
    """Workflow that produced these artifacts."""

    session_id: str | None = None
    """Session that produced these artifacts."""

    phase_id: str | None = None
    """Phase that produced these artifacts."""

    # Storage options
    storage_provider: str | None = None
    """Override storage provider. None = use default from settings."""

    custom_prefix: str | None = None
    """Custom storage prefix. None = auto-generate from IDs."""
