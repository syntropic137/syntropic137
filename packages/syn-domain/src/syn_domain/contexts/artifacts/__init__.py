"""Artifacts bounded context - stores workflow phase outputs.

This context provides aggregates, commands, and events for storing
artifacts produced by workflow phases.

Usage:
    from syn_domain.contexts.artifacts import (
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

from syn_domain.contexts.artifacts._shared import (
    ArtifactAggregate,
    ArtifactType,
    ContentType,
    compute_content_hash,
)
from syn_domain.contexts.artifacts.domain.commands.DeleteArtifactCommand import (
    DeleteArtifactCommand,
)
from syn_domain.contexts.artifacts.domain.commands.UpdateArtifactCommand import (
    UpdateArtifactCommand,
)
from syn_domain.contexts.artifacts.domain.services import (
    ArtifactQueryService,
    ArtifactQueryServiceProtocol,
)
from syn_domain.contexts.artifacts.ports.ArtifactContentStoragePort import (
    ArtifactContentStoragePort,
)
from syn_domain.contexts.artifacts.slices.create_artifact import (
    ArtifactCreatedEvent,
    CreateArtifactCommand,
)
from syn_domain.contexts.artifacts.slices.manage_artifact.ManageArtifactHandler import (
    ManageArtifactHandler,
)
from syn_domain.contexts.artifacts.slices.upload_artifact import (
    ArtifactUploadedEvent,
    UploadArtifactCommand,
)

__all__ = [
    "ArtifactAggregate",
    "ArtifactContentStoragePort",
    "ArtifactCreatedEvent",
    "ArtifactQueryService",
    "ArtifactQueryServiceProtocol",
    "ArtifactType",
    "ArtifactUploadedEvent",
    "ContentType",
    "CreateArtifactCommand",
    "DeleteArtifactCommand",
    "ManageArtifactHandler",
    "UpdateArtifactCommand",
    "UploadArtifactCommand",
    "compute_content_hash",
]
