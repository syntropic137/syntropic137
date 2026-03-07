"""Repo Unassigned from System domain event.

Emitted when a repository is unassigned from a system.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.RepoUnassignedFromSystem", "v1")
class RepoUnassignedFromSystemEvent(DomainEvent):
    """Event emitted when a repository is unassigned from a system.

    Attributes:
        repo_id: Unique identifier for the repository.
        previous_system_id: ID of the system the repo was unassigned from.
    """

    repo_id: str
    previous_system_id: str

    @field_validator("repo_id")
    @classmethod
    def validate_repo_id(cls, v: str) -> str:
        """Ensure repo_id is provided."""
        if not v:
            raise ValueError("repo_id is required")
        return v
