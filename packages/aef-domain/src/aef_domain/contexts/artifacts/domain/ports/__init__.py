"""Artifact domain ports - interfaces for external dependencies.

Ports define what the domain needs from the outside world.
Adapters implement these ports with specific technologies.

See: Ports & Adapters (Hexagonal Architecture)
"""

from aef_domain.contexts.artifacts.domain.ports.artifact_storage import (
    ArtifactContentStoragePort,
    StorageResult,
)

__all__ = [
    "ArtifactContentStoragePort",
    "StorageResult",
]

