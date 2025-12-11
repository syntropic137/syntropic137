"""Workspace destruction events."""

from aef_domain.contexts.workspaces.destroy_workspace.WorkspaceCommandExecutedEvent import (
    WorkspaceCommandExecutedEvent,
)
from aef_domain.contexts.workspaces.destroy_workspace.WorkspaceDestroyedEvent import (
    WorkspaceDestroyedEvent,
)
from aef_domain.contexts.workspaces.destroy_workspace.WorkspaceDestroyingEvent import (
    WorkspaceDestroyingEvent,
)
from aef_domain.contexts.workspaces.destroy_workspace.WorkspaceErrorEvent import (
    WorkspaceErrorEvent,
)

__all__ = [
    "WorkspaceCommandExecutedEvent",
    "WorkspaceDestroyedEvent",
    "WorkspaceDestroyingEvent",
    "WorkspaceErrorEvent",
]
