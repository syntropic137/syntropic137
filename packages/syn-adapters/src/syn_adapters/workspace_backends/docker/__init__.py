"""Docker workspace adapters.

This module provides Docker-based sidecar proxy management.

For workspace isolation, use WorkspaceService.create() which uses
agentic_isolation from agentic-primitives.

Available:
- DockerSidecarAdapter: Manages Envoy sidecar proxy containers

See ADR-021 (Isolated Workspace Architecture).
"""

from syn_adapters.workspace_backends.docker.docker_sidecar_adapter import (
    DockerSidecarAdapter,
)

__all__ = [
    "DockerSidecarAdapter",
]
