"""Docker workspace adapters.

DEPRECATED: Use agentic_isolation adapters via WorkspaceService.create() instead.

The new recommended approach:
    from aef_adapters.workspace_backends.service import WorkspaceService

    service = WorkspaceService.create()  # Uses agentic_isolation internally

Still in use:
- DockerSidecarAdapter: Manages Envoy sidecar proxy (still needed)

Deprecated (use agentic_isolation):
- DockerIsolationAdapter: Replaced by AgenticIsolationAdapter
- DockerEventStreamAdapter: Replaced by AgenticEventStreamAdapter

See ADR-021 (Isolated Workspace Architecture).
"""

from aef_adapters.workspace_backends.docker.docker_event_stream_adapter import (
    DockerEventStreamAdapter,
)
from aef_adapters.workspace_backends.docker.docker_isolation_adapter import (
    DockerIsolationAdapter,
)
from aef_adapters.workspace_backends.docker.docker_sidecar_adapter import (
    DockerSidecarAdapter,
)

__all__ = [
    "DockerEventStreamAdapter",
    "DockerIsolationAdapter",
    "DockerSidecarAdapter",
]
