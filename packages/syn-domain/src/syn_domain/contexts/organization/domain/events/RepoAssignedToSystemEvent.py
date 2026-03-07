"""Repo Assigned to System domain event.

Emitted when a repository is assigned to a system.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.RepoAssignedToSystem", "v1")
class RepoAssignedToSystemEvent(DomainEvent):
    """Event emitted when a repository is assigned to a system.

    Attributes:
        repo_id: Unique identifier for the repository.
        system_id: ID of the system the repo is being assigned to.
    """

    repo_id: str
    system_id: str

    @field_validator("repo_id")
    @classmethod
    def validate_repo_id(cls, v: str) -> str:
        """Ensure repo_id is provided."""
        if not v:
            raise ValueError("repo_id is required")
        return v

    @field_validator("system_id")
    @classmethod
    def validate_system_id(cls, v: str) -> str:
        """Ensure system_id is provided."""
        if not v:
            raise ValueError("system_id is required")
        return v
