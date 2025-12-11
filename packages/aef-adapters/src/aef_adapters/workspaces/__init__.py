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
from aef_adapters.workspaces.docker_hardened import HardenedDockerWorkspace
from aef_adapters.workspaces.e2b import E2BWorkspace
from aef_adapters.workspaces.firecracker import FirecrackerWorkspace
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
    "E2BWorkspace",
    "FirecrackerWorkspace",
    "GVisorWorkspace",
    "HardenedDockerWorkspace",
    "IsolatedWorkspace",
    "IsolatedWorkspaceConfig",
    "IsolatedWorkspaceProtocol",
    "LocalWorkspace",
    "NonIsolatedWorkspaceError",
    "RouterStats",
    "WorkspaceProtocol",
    "WorkspaceRouter",
    "get_workspace_router",
    "reset_workspace_router",
]
