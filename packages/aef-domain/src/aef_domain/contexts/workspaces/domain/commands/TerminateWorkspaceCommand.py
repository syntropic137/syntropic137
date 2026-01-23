"""TerminateWorkspaceCommand - command to terminate a workspace."""

from __future__ import annotations

from dataclasses import dataclass

from event_sourcing import Command


@dataclass
class TerminateWorkspaceCommand(Command):
    """Command to terminate a workspace.

    Triggers cleanup of isolation, sidecar, and token revocation.

    Attributes:
        workspace_id: Workspace to terminate
        reason: Termination reason for audit trail
        force: Force termination even if operations in progress
    """

    workspace_id: str
    reason: str = "completed"  # completed, failed, timeout, cancelled, error

    # Force cleanup even if operations in progress
    force: bool = False

    @property
    def aggregate_id(self) -> str:
        """Return workspace_id as the aggregate ID."""
        return self.workspace_id
