"""Artifact domain services."""

from aef_domain.contexts.artifacts.domain.services.artifact_query_service import (
    ArtifactQueryService,
    ArtifactQueryServiceProtocol,
)

__all__ = [
    "ArtifactQueryService",
    "ArtifactQueryServiceProtocol",
]
