"""Workspace adapters - isolated execution environments for agents.

This module provides workspace implementations for agentic execution:
- LocalWorkspace: File-based workspace in temp directories (MVP)
- DockerWorkspace: Isolated Docker containers (future)
- CloudWorkspace: Cloud-based execution (future)

Quick Start:
    from aef_adapters.workspaces import LocalWorkspace, WorkspaceConfig

    config = WorkspaceConfig(session_id="my-session")
    async with LocalWorkspace.create(config) as workspace:
        # Workspace has hooks configured from agentic-primitives
        # Execute agent in workspace.path
        ...
        # Artifacts collected on exit
"""

from aef_adapters.workspaces.local import LocalWorkspace
from aef_adapters.workspaces.protocol import WorkspaceProtocol

__all__ = [
    "LocalWorkspace",
    "WorkspaceProtocol",
]
