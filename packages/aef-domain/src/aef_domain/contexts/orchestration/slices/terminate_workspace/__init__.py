"""Terminate workspace slice - commands and events."""

from aef_domain.contexts.orchestration.domain.commands import TerminateWorkspaceCommand
from aef_domain.contexts.orchestration.domain.events import WorkspaceTerminatedEvent

__all__ = [
    "TerminateWorkspaceCommand",
    "WorkspaceTerminatedEvent",
]
