"""Repo Claimed domain event.

Emitted when a repo name is claimed within an organization,
enforcing uniqueness via the stream-per-unique-value pattern.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.RepoClaimed", "v1")
class RepoClaimedEvent(DomainEvent):
    """Event emitted when a repository name is claimed.

    Attributes:
        claim_id: Deterministic claim ID (hash of org+provider+full_name).
        organization_id: ID of the organization.
        provider: Git hosting provider (github/gitea/gitlab).
        full_name: Full repository name (e.g. "owner/repo").
        repo_id: ID of the RepoAggregate that owns this claim.
    """

    claim_id: str
    organization_id: str
    provider: str
    full_name: str
    repo_id: str

    @field_validator("claim_id")
    @classmethod
    def validate_claim_id(cls, v: str) -> str:
        """Ensure claim_id is provided."""
        if not v:
            raise ValueError("claim_id is required")
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
