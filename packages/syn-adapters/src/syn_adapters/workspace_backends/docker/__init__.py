"""Docker workspace adapters.

This module provides Docker-based sidecar proxy management.

For workspace isolation, use WorkspaceService.create() which uses
agentic_isolation from agentic-primitives.

Available:
- DockerSidecarAdapter: Per-workspace Envoy sidecar containers (legacy)
- SharedEnvoyAdapter: Shared Envoy proxy for credential injection (ISS-43)

See ADR-021 (Isolated Workspace Architecture).
"""

from syn_adapters.workspace_backends.docker.docker_sidecar_adapter import (
    DockerSidecarAdapter,
)
from syn_adapters.workspace_backends.docker.shared_envoy_adapter import (
    SharedEnvoyAdapter,
)

__all__ = [
    "DockerSidecarAdapter",
    "SharedEnvoyAdapter",
]
