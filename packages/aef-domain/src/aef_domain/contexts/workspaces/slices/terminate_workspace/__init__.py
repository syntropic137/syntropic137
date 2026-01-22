"""Workspace termination slice - commands and events."""

from aef_domain.contexts.workspaces.domain.commands.TerminateWorkspaceCommand import (
    TerminateWorkspaceCommand,
)
from aef_domain.contexts.workspaces.domain.events.WorkspaceTerminatedEvent import (
    WorkspaceTerminatedEvent,
)

__all__ = [
    "TerminateWorkspaceCommand",
    "WorkspaceTerminatedEvent",
]
