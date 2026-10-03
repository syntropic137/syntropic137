"""Shared components for artifacts bounded context."""

from syn_domain.contexts.artifacts._shared.value_objects import (
    UNREPORTED_AGENT,
    AgentIdentity,
    ArtifactType,
    ContentType,
    PhaseOutputFile,
    compute_content_hash,
)
from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
    ArtifactAggregate,
)

__all__ = [
    "UNREPORTED_AGENT",
    "AgentIdentity",
    "ArtifactAggregate",
    "ArtifactType",
    "ContentType",
    "PhaseOutputFile",
    "compute_content_hash",
]
