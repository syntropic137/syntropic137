"""Shared components for artifacts bounded context."""

from aef_domain.contexts.artifacts._shared.value_objects import (
    ArtifactType,
    ContentType,
    compute_content_hash,
)
from aef_domain.contexts.artifacts.domain.ArtifactAggregate import ArtifactAggregate

__all__ = [
    "ArtifactAggregate",
    "ArtifactType",
    "ContentType",
    "compute_content_hash",
]
