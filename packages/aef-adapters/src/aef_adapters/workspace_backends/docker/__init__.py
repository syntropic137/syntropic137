"""Docker workspace adapters for development and production.

This module provides Docker-based implementations of workspace ports:
- DockerIsolationAdapter: Creates/manages Docker containers
- DockerSidecarAdapter: Manages Envoy sidecar proxy containers
- DockerEventStreamAdapter: Streams stdout from containers

These adapters implement the port interfaces from aef_domain.contexts.workspaces.

Usage:
    from aef_adapters.workspace_backends.docker import DockerIsolationAdapter

    adapter = DockerIsolationAdapter()
    handle = await adapter.create(config)
    result = await adapter.execute(handle, ["python", "script.py"])
    await adapter.destroy(handle)

See ADR-021 (Isolated Workspace Architecture) and ADR-022 (Secure Token Architecture).
"""

from aef_adapters.workspace_backends.docker.docker_isolation_adapter import (
    DockerIsolationAdapter,
)
from aef_adapters.workspace_backends.docker.docker_sidecar_adapter import (
    DockerSidecarAdapter,
)

__all__ = [
    "DockerIsolationAdapter",
    "DockerSidecarAdapter",
]
