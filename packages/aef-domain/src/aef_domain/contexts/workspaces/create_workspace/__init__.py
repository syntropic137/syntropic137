"""Workspace creation events."""

from aef_domain.contexts.workspaces.create_workspace.WorkspaceCreatedEvent import (
    WorkspaceCreatedEvent,
)
from aef_domain.contexts.workspaces.create_workspace.WorkspaceCreatingEvent import (
    WorkspaceCreatingEvent,
)

__all__ = [
    "WorkspaceCreatedEvent",
    "WorkspaceCreatingEvent",
]
