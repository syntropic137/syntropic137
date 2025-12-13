"""Installation Revoked domain event.

Emitted when a GitHub App installation is uninstalled/revoked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4


@dataclass(frozen=True)
class InstallationRevokedEvent:
    """Event emitted when the GitHub App installation is revoked.

    This event is triggered by the GitHub webhook when a user uninstalls
    the app from their account or organization.

    Attributes:
        event_id: Unique identifier for this event.
        event_type: Type identifier for event routing.
        installation_id: GitHub installation ID that was revoked.
        account_name: GitHub account login name.
        occurred_at: When the revocation occurred.
    """

    event_type: ClassVar[str] = "github.InstallationRevoked"

    installation_id: str
    account_name: str
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the event."""
        if not self.installation_id:
            raise ValueError("installation_id is required")

    @classmethod
    def from_webhook(cls, payload: dict) -> InstallationRevokedEvent:
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
