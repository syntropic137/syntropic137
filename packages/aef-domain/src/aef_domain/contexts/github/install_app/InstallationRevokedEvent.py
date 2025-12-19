"""Installation Revoked domain event.

Emitted when a GitHub App installation is uninstalled/revoked.
"""

from __future__ import annotations

from typing import Any

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("github.InstallationRevoked", "v1")
class InstallationRevokedEvent(DomainEvent):
    """Event emitted when the GitHub App installation is revoked.

    This event is triggered by the GitHub webhook when a user uninstalls
    the app from their account or organization.

    Inherits from DomainEvent which provides:
    - Immutability (frozen=True)
    - Strict validation (extra='forbid')
    - JSON serialization
    """

    installation_id: str
    account_name: str

    @field_validator("installation_id")
    @classmethod
    def validate_installation_id(cls, v: str) -> str:
        """Ensure installation_id is provided."""
        if not v:
            raise ValueError("installation_id is required")
        return v

    @classmethod
    def from_webhook(cls, payload: dict[str, Any]) -> InstallationRevokedEvent:
        """Create an event from a GitHub webhook payload.

        Args:
            payload: The webhook payload dict.

        Returns:
            InstallationRevokedEvent instance.
        """
        installation = payload.get("installation", {})
        account = installation.get("account", {})

        return cls(
            installation_id=str(installation.get("id", "")),
            account_name=account.get("login", ""),
        )
