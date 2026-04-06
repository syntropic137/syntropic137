"""Repo summary read model.

Represents the current state of a repository, projected from events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RepoSummary:
    """Read model for a repository summary.

    Attributes:
        repo_id: Unique identifier for the repository.
        organization_id: ID of the organization this repo belongs to.
        system_id: ID of the system this repo is assigned to (empty if unassigned).
        provider: Git hosting provider (github/gitea/gitlab).
        provider_repo_id: Provider-assigned repository ID.
        full_name: Full repository name (e.g. "owner/repo").
        owner: Repository owner username or organization name.
        default_branch: Default branch name.
        installation_id: GitHub App installation ID (if applicable).
        is_private: Whether the repository is private.
        created_by: User or agent that registered the repo.
        created_at: When the repo was registered.
    """

    repo_id: str
    organization_id: str
    system_id: str = ""
    provider: str = "github"
    provider_repo_id: str = ""
    full_name: str = ""
    owner: str = ""
    default_branch: str = "main"
    installation_id: str = ""
    is_private: bool = False
    created_by: str = ""
    created_at: datetime | None = None
    is_deregistered: bool = False
