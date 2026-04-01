"""Deregister Repo command.

Command to soft-delete (deregister) a repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class DeregisterRepoCommand:
    """Command to deregister (soft-delete) a repository.

    Deregistered repos are hidden from listings but preserved
    in the event store for historical reference.

    Attributes:
        repo_id: ID of the repo to deregister.
        deregistered_by: User or agent performing the deregistration.
        command_id: Unique identifier for this command.
    """

    repo_id: str
    deregistered_by: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        """Map command to aggregate instance."""
        return self.repo_id

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.repo_id:
            raise ValueError("repo_id is required")
