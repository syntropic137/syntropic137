"""Claim Repo command.

Command to claim a repository name within an organization,
enforcing uniqueness via the stream-per-unique-value pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class ClaimRepoCommand:
    """Command to claim a repository name.

    Attributes:
        organization_id: ID of the organization.
        provider: Git hosting provider (github/gitea/gitlab).
        full_name: Full repository name (e.g. "owner/repo").
        repo_id: Pre-generated ID for the RepoAggregate.
        aggregate_id: Deterministic claim ID (hash of org+provider+full_name).
        command_id: Unique identifier for this command.
    """

    organization_id: str
    provider: str
    full_name: str
    repo_id: str
    aggregate_id: str = ""
    command_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate the command."""
        if not self.organization_id:
            raise ValueError("organization_id is required")
        if not self.full_name:
            raise ValueError("full_name is required")
        if not self.provider:
            raise ValueError("provider is required")
        if not self.repo_id:
            raise ValueError("repo_id is required")
        if not self.aggregate_id:
            raise ValueError("aggregate_id is required")
