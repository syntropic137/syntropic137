"""Terminate workspace slice - commands and events."""

from syn_domain.contexts.orchestration.domain.commands import TerminateWorkspaceCommand
from syn_domain.contexts.orchestration.domain.events import WorkspaceTerminatedEvent

__all__ = [
    "TerminateWorkspaceCommand",
    "WorkspaceTerminatedEvent",
]
