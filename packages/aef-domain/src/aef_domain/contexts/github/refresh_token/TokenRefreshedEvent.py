"""Token Refreshed domain event.

Emitted when an installation token is successfully refreshed.
"""

from __future__ import annotations

from datetime import datetime

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("github.TokenRefreshed", "v1")
class TokenRefreshedEvent(DomainEvent):
    """Event emitted when an installation token is refreshed.

    For security, we never store the raw token in events.
    Only a hash is stored for audit/debugging purposes.

    Inherits from DomainEvent which provides:
    - Immutability (frozen=True)
    - Strict validation (extra='forbid')
    - JSON serialization
    """

    installation_id: str
    token_hash: str
    expires_at: datetime
    permissions: dict[str, str] = {}

    @field_validator("installation_id")
    @classmethod
    def validate_installation_id(cls, v: str) -> str:
        """Ensure installation_id is provided."""
        if not v:
            raise ValueError("installation_id is required")
        return v

    @field_validator("token_hash")
    @classmethod
    def validate_token_hash(cls, v: str) -> str:
        """Ensure token_hash is provided."""
        if not v:
            raise ValueError("token_hash is required")
        return v

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: datetime) -> datetime:
        """Ensure expires_at is timezone-aware."""
        if v.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        return v
