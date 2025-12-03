"""Artifact handling for agentic execution.

This module provides types for:
- Collecting artifacts from workspace outputs
- Bundling artifacts for phase-to-phase context flow
- Injecting artifact context into subsequent phases

These are in-flight types for workspace operations.
For persistent storage, see aef_domain.contexts.artifacts.
"""

from aef_adapters.artifacts.bundle import (
    ArtifactBundle,
    ArtifactFile,
    ArtifactMetadata,
    ArtifactType,
    PhaseContext,
)

__all__ = [
    "ArtifactBundle",
    "ArtifactFile",
    "ArtifactMetadata",
    "ArtifactType",
    "PhaseContext",
]
