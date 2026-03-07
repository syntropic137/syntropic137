"""Assign Repo to System command.

Command to assign a repository to a system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class AssignRepoToSystemCommand:
    """Command to assign a repository to a system.

    Attributes:
        repo_id: ID of the repository to assign.
        system_id: ID of the system to assign the repo to.
        command_id: Unique identifier for this command.
    """

    repo_id: str
    system_id: str
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        return self.repo_id

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.repo_id:
            raise ValueError("repo_id is required")
        if not self.system_id:
            raise ValueError("system_id is required")
