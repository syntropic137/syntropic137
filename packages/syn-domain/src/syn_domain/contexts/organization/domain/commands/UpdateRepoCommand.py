"""Update Repo command.

Command to update mutable fields of a registered repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class UpdateRepoCommand:
    """Command to update a repository's mutable fields.

    Only non-None fields are applied. Identity fields (provider, full_name,
    owner, provider_repo_id) are immutable and cannot be changed.

    Attributes:
        repo_id: ID of the repo to update.
        default_branch: New default branch name.
        is_private: New privacy flag.
        installation_id: New GitHub App installation ID.
        updated_by: User or agent performing the update.
        command_id: Unique identifier for this command.
    """

    repo_id: str
    default_branch: str | None = None
    is_private: bool | None = None
    installation_id: str | None = None
    updated_by: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def aggregate_id(self) -> str:
        """Map command to aggregate instance."""
        return self.repo_id

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.repo_id:
            raise ValueError("repo_id is required")
        if self.default_branch is None and self.is_private is None and self.installation_id is None:
            raise ValueError("at least one field to update is required")
