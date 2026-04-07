"""Register Repo command.

Command to register a new repository within an organization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class RegisterRepoCommand:
    """Command to register a new repository.

    Attributes:
        organization_id: ID of the organization this repo belongs to.
        provider: Git hosting provider ("github", "gitea", or "gitlab").
        full_name: Full repository name (e.g. "owner/repo").
        provider_repo_id: Provider-assigned repository ID.
        owner: Repository owner username or organization name.
        default_branch: Default branch name.
        installation_id: GitHub App installation ID (if applicable).
        is_private: Whether the repository is private.
        created_by: User or agent registering the repo.
        aggregate_id: Optional pre-assigned aggregate ID.
        command_id: Unique identifier for this command.
    """

    organization_id: str = "_unaffiliated"
    provider: str = "github"
    full_name: str = ""
    provider_repo_id: str = ""
    owner: str = ""
    default_branch: str = "main"
    installation_id: str = ""
    is_private: bool = False
    created_by: str = ""
    aggregate_id: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.full_name:
            raise ValueError("full_name is required")
        if not self.provider:
            raise ValueError("provider is required")
        if self.provider not in ("github", "gitea", "gitlab"):
            raise ValueError("provider must be one of: github, gitea, gitlab")
        if self.organization_id == "":
            raise ValueError(
                "organization_id cannot be empty; use '_unaffiliated' for org-less repos"
            )
