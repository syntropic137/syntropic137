"""Artifacts bounded context - stores workflow phase outputs.

This context provides aggregates, commands, and events for storing
artifacts produced by workflow phases.

Usage:
    from aef_domain.contexts.artifacts import (
        ArtifactAggregate,
        CreateArtifactCommand,
        ArtifactType,
    )

    # Create artifact
    artifact = ArtifactAggregate()
    artifact.create_artifact(CreateArtifactCommand(
        workflow_id="wf-123",
        phase_id="research",
        artifact_type=ArtifactType.RESEARCH_SUMMARY,
        content="# Research Summary\\n\\n...",
        title="Research findings on AI agents",
    ))
"""

from aef_domain.contexts.artifacts._shared import (
    ArtifactAggregate,
    ArtifactType,
    ContentType,
    compute_content_hash,
)
from aef_domain.contexts.artifacts.create_artifact import (
    ArtifactCreatedEvent,
    CreateArtifactCommand,
)

__all__ = [
    "ArtifactAggregate",
    "ArtifactCreatedEvent",
    "ArtifactType",
    "ContentType",
    "CreateArtifactCommand",
    "compute_content_hash",
]
