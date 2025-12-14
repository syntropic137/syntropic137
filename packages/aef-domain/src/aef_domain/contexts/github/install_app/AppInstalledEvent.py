"""App Installed domain event.

Emitted when a GitHub App is installed in an organization or user account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4


@dataclass(frozen=True)
class AppInstalledEvent:
    """Event emitted when the GitHub App is installed.

    This event is triggered by the GitHub webhook when a user installs
    the app on their account or organization.

    Attributes:
        event_id: Unique identifier for this event.
        event_type: Type identifier for event routing.
        installation_id: GitHub installation ID.
        account_id: GitHub account ID (user or org).
        account_name: GitHub account login name.
        account_type: 'User' or 'Organization'.
        repositories: Tuple of repository full names accessible to the installation.
        permissions: Dict of permission name to level ('read', 'write', 'admin').
        occurred_at: When the installation occurred.
    """

    event_type: ClassVar[str] = "github.AppInstalled"

    installation_id: str
    account_id: int
    account_name: str
    account_type: str
    repositories: tuple[str, ...] = field(default_factory=tuple)
    permissions: dict[str, str] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the event."""
        if not self.installation_id:
            raise ValueError("installation_id is required")
        if not self.account_name:
            raise ValueError("account_name is required")
        if self.account_type not in ("User", "Organization"):
            raise ValueError(f"Invalid account_type: {self.account_type}")

    @classmethod
    def from_webhook(cls, payload: dict) -> AppInstalledEvent:
        """Create an event from a GitHub webhook payload.

        Args:
            payload: The webhook payload dict.

        Returns:
            AppInstalledEvent instance.
        """
        installation = payload.get("installation", {})
        account = installation.get("account", {})

        # Get repositories if provided (only for 'selected' repository access)
        repositories = tuple(
            repo.get("full_name", "")
            for repo in payload.get("repositories", [])
            if repo.get("full_name")
        )

        return cls(
            installation_id=str(installation.get("id", "")),
            account_id=account.get("id", 0),
            account_name=account.get("login", ""),
            account_type=account.get("type", "User"),
            repositories=repositories,
            permissions=installation.get("permissions", {}),
        )
