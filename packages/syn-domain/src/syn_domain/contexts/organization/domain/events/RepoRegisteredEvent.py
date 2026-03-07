"""Repo Registered domain event.

Emitted when a new repository is registered within an organization.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.RepoRegistered", "v1")
class RepoRegisteredEvent(DomainEvent):
    """Event emitted when a repository is registered.

    Attributes:
        repo_id: Unique identifier for the repository.
        organization_id: ID of the organization this repo belongs to.
        provider: Git hosting provider (github/gitea/gitlab).
        provider_repo_id: Provider-assigned repository ID.
        full_name: Full repository name (e.g. "owner/repo").
        owner: Repository owner username or organization name.
        default_branch: Default branch name.
        installation_id: GitHub App installation ID (if applicable).
        is_private: Whether the repository is private.
        created_by: User or agent that registered the repo.
    """

    repo_id: str
    organization_id: str
    provider: str
    provider_repo_id: str = ""
    full_name: str
    owner: str = ""
    default_branch: str = "main"
    installation_id: str = ""
    is_private: bool = False
    created_by: str = ""

    @field_validator("repo_id")
    @classmethod
    def validate_repo_id(cls, v: str) -> str:
        """Ensure repo_id is provided."""
        if not v:
            raise ValueError("repo_id is required")
        return v

    @field_validator("organization_id")
    @classmethod
    def validate_organization_id(cls, v: str) -> str:
        """Ensure organization_id is provided."""
        if not v:
            raise ValueError("organization_id is required")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        """Ensure full_name is provided."""
        if not v:
            raise ValueError("full_name is required")
        return v
