"""Repo Claim Released domain event.

Emitted when a repo claim is released, allowing the name to be re-registered.
"""

from __future__ import annotations

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("organization.RepoClaimReleased", "v1")
class RepoClaimReleasedEvent(DomainEvent):
    """Event emitted when a repository claim is released.

    Attributes:
        claim_id: Deterministic claim ID being released.
        repo_id: ID of the repo that was deregistered.
    """

    claim_id: str
    repo_id: str

    @field_validator("claim_id")
    @classmethod
    def validate_claim_id(cls, v: str) -> str:
        """Ensure claim_id is provided."""
        if not v:
            raise ValueError("claim_id is required")
        return v
