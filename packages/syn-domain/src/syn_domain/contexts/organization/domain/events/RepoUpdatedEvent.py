"""Repo Updated domain event.

Emitted when a repository's mutable fields are updated.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.RepoUpdated", "v1")
class RepoUpdatedEvent(DomainEvent):
    """Event emitted when a repository is updated.

    Only non-None fields were changed. Consumers should apply
    only the fields that are present.

    Attributes:
        repo_id: Unique identifier for the repository.
        default_branch: Updated default branch name, or None if unchanged.
        is_private: Updated privacy flag, or None if unchanged.
        installation_id: Updated installation ID, or None if unchanged.
        updated_by: User or agent that performed the update.
    """

    repo_id: str
    default_branch: str | None = None
    is_private: bool | None = None
    installation_id: str | None = None
    updated_by: str = ""

    @field_validator("repo_id")
    @classmethod
    def validate_repo_id(cls, v: str) -> str:
        """Ensure repo_id is provided."""
        if not v:
            raise ValueError("repo_id is required")
        return v
