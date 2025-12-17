"""Workspace termination slice - commands and events."""

from aef_domain.contexts.workspaces.terminate_workspace.TerminateWorkspaceCommand import (
    TerminateWorkspaceCommand,
)
from aef_domain.contexts.workspaces.terminate_workspace.WorkspaceTerminatedEvent import (
    WorkspaceTerminatedEvent,
)

__all__ = [
    "TerminateWorkspaceCommand",
    "WorkspaceTerminatedEvent",
]
