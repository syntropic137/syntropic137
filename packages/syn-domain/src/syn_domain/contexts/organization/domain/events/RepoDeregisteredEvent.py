"""Repo Deregistered domain event.

Emitted when a repository is soft-deleted (deregistered).
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.RepoDeregistered", "v1")
class RepoDeregisteredEvent(DomainEvent):
    """Event emitted when a repository is deregistered.

    Deregistered repos are hidden from listings but preserved
    in the event store for historical reference.

    Attributes:
        repo_id: Unique identifier for the repository.
        deregistered_by: User or agent that performed the deregistration.
    """

    repo_id: str
    organization_id: str = ""
    system_id: str = ""
    deregistered_by: str = ""

    @field_validator("repo_id")
    @classmethod
    def validate_repo_id(cls, v: str) -> str:
        """Ensure repo_id is provided."""
        if not v:
            raise ValueError("repo_id is required")
        return v
