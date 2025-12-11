"""Workspace adapters - isolated execution environments for agents.

This module provides workspace implementations for agentic execution:
- LocalWorkspace: File-based workspace in temp directories (development/testing)
- BaseIsolatedWorkspace: Abstract base for all isolated backends (ADR-021)

Isolated Backends (all production use - agents are isolated by default):
- GVisorWorkspace: Docker + gVisor runtime (Milestone 3)
- HardenedDockerWorkspace: Docker with security hardening (Milestone 4)
- FirecrackerWorkspace: Firecracker MicroVMs (Milestone 5)
- E2BWorkspace: E2B cloud sandboxes (Milestone 6)

Quick Start (Development):
    from aef_adapters.workspaces import LocalWorkspace
    from aef_adapters.agents.agentic_types import WorkspaceConfig

    config = WorkspaceConfig(session_id="my-session")
    async with LocalWorkspace.create(config) as workspace:
        # Workspace has hooks configured from agentic-primitives
        # Execute agent in workspace.path
        ...
        # Artifacts collected on exit

Production (with isolation):
    from aef_adapters.workspaces import BaseIsolatedWorkspace, IsolatedWorkspaceConfig

    # See WorkspaceRouter for automatic backend selection (Milestone 7)

See ADR-021: Isolated Workspace Architecture
"""

from aef_adapters.workspaces.base import BaseIsolatedWorkspace
from aef_adapters.workspaces.collector_emitter import (
    CollectorEmitter,
    InMemoryCollectorEmitter,
)
from aef_adapters.workspaces.docker_hardened import HardenedDockerWorkspace
from aef_adapters.workspaces.e2b import E2BWorkspace
from aef_adapters.workspaces.env_injector import (
    EnvInjector,
    InjectedEnvVar,
    get_env_injector,
)
from aef_adapters.workspaces.events import (
    WorkspaceEventEmitter,
    configure_workspace_emitter,
    get_workspace_emitter,
)
from aef_adapters.workspaces.firecracker import FirecrackerWorkspace
from aef_adapters.workspaces.git import (
    ExecutionContext,
    GitInjector,
    build_commit_message,
    get_git_injector,
)
from aef_adapters.workspaces.gvisor import GVisorWorkspace
from aef_adapters.workspaces.local import LocalWorkspace, NonIsolatedWorkspaceError
from aef_adapters.workspaces.protocol import IsolatedWorkspaceProtocol, WorkspaceProtocol
from aef_adapters.workspaces.router import (
    RouterStats,
    WorkspaceRouter,
    get_workspace_router,
    reset_workspace_router,
)
from aef_adapters.workspaces.types import IsolatedWorkspace, IsolatedWorkspaceConfig

__all__ = [
    "BaseIsolatedWorkspace",
    "CollectorEmitter",
    "E2BWorkspace",
    "EnvInjector",
    "ExecutionContext",
    "FirecrackerWorkspace",
    "GVisorWorkspace",
    "GitInjector",
    "HardenedDockerWorkspace",
    "InMemoryCollectorEmitter",
    "InjectedEnvVar",
    "IsolatedWorkspace",
    "IsolatedWorkspaceConfig",
    "IsolatedWorkspaceProtocol",
    "LocalWorkspace",
    "NonIsolatedWorkspaceError",
    "RouterStats",
    "WorkspaceEventEmitter",
    "WorkspaceProtocol",
    "WorkspaceRouter",
    "build_commit_message",
    "configure_workspace_emitter",
    "get_env_injector",
    "get_git_injector",
    "get_workspace_emitter",
    "get_workspace_router",
    "reset_workspace_router",
]
