"""Unassign Repo from System command.

Command to remove a repository's assignment from a system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class UnassignRepoFromSystemCommand:
    """Command to unassign a repository from its current system.

    Attributes:
        repo_id: ID of the repository to unassign.
        command_id: Unique identifier for this command.
    """

    repo_id: str
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.repo_id

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.repo_id:
            raise ValueError("repo_id is required")
