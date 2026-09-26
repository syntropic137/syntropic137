"""Artifact domain ports - interfaces for external dependencies.

Ports define what the domain needs from the outside world.
Adapters implement these ports with specific technologies.

See: Ports & Adapters (Hexagonal Architecture)
"""

from syn_domain.contexts.artifacts.ports.ArtifactContentStoragePort import (
    ArtifactContentStoragePort,
    ArtifactStorageError,
    StorageResult,
)

__all__ = [
    "ArtifactContentStoragePort",
    "ArtifactStorageError",
    "StorageResult",
]
