"""Token Refreshed domain event.

Emitted when an installation token is successfully refreshed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4


@dataclass(frozen=True)
class TokenRefreshedEvent:
    """Event emitted when an installation token is refreshed.

    For security, we never store the raw token in events.
    Only a hash is stored for audit/debugging purposes.

    Attributes:
        event_id: Unique identifier for this event.
        event_type: Type identifier for event routing.
        installation_id: GitHub installation ID.
        token_hash: SHA-256 hash of the token (first 12 chars).
        expires_at: When the new token expires.
        permissions: Dict of permission name to level.
        occurred_at: When the refresh occurred.
    """

    event_type: ClassVar[str] = "github.TokenRefreshed"

    installation_id: str
    token_hash: str
    expires_at: datetime
    permissions: dict[str, str] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the event."""
        if not self.installation_id:
            raise ValueError("installation_id is required")
        if not self.token_hash:
            raise ValueError("token_hash is required")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
