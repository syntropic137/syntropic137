"""WorkspaceService - orchestrates workspace lifecycle.

This module provides the WorkspaceService facade that composes all workspace
adapters into a single, easy-to-use interface for the WorkflowExecutionEngine.

The service orchestrates:
- Container creation and destruction (DockerIsolationAdapter)
- Sidecar proxy management (DockerSidecarAdapter)
- Token vending and injection (TokenVendingServiceAdapter, SidecarTokenInjectionAdapter)
- Event streaming (DockerEventStreamAdapter)
- State management (WorkspaceAggregate)

Usage:
    from aef_adapters.workspace_backends.service import WorkspaceService

    service = WorkspaceService.create_docker()  # Production
    # OR
    service = WorkspaceService.create_memory()  # Testing

    async with service.create_workspace(config) as workspace:
        result = await workspace.execute(["python", "script.py"])
        async for line in workspace.stream(["agent-runner"]):
            process(line)

See ADR-021, ADR-022, ADR-023 for architectural decisions.
"""

from aef_adapters.workspace_backends.service.workspace_service import (
    ManagedWorkspace,
    WorkspaceService,
    WorkspaceServiceConfig,
)

__all__ = [
    "ManagedWorkspace",
    "WorkspaceService",
    "WorkspaceServiceConfig",
]
