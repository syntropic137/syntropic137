"""Domain events for artifacts context.

This module contains events for artifact lifecycle tracking.
"""

from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import (
    ArtifactCreatedEvent,
)
from syn_domain.contexts.artifacts.domain.events.ArtifactUploadedEvent import (
    ArtifactUploadedEvent,
)

__all__ = [
    "ArtifactCreatedEvent",
    "ArtifactUploadedEvent",
]
