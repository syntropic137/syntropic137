"""App Installed domain event.

Emitted when a GitHub App is installed in an organization or user account.
"""

from __future__ import annotations

from typing import Any

from event_sourcing import DomainEvent, event
from pydantic import field_validator


@event("github.AppInstalled", "v1")
class AppInstalledEvent(DomainEvent):
    """Event emitted when the GitHub App is installed.

    This event is triggered by the GitHub webhook when a user installs
    the app on their account or organization.

    Inherits from DomainEvent which provides:
    - Immutability (frozen=True)
    - Strict validation (extra='forbid')
    - JSON serialization
    """

    installation_id: str
    account_id: int
    account_name: str
    account_type: str
    repositories: tuple[str, ...] = ()
    permissions: dict[str, str] = {}

    @field_validator("installation_id")
    @classmethod
    def validate_installation_id(cls, v: str) -> str:
        """Ensure installation_id is provided."""
        if not v:
            raise ValueError("installation_id is required")
        return v

    @field_validator("account_name")
    @classmethod
    def validate_account_name(cls, v: str) -> str:
        """Ensure account_name is provided."""
        if not v:
            raise ValueError("account_name is required")
        return v

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str) -> str:
        """Ensure account_type is valid."""
        if v not in ("User", "Organization"):
            raise ValueError(f"Invalid account_type: {v}")
        return v

    @classmethod
    def from_webhook(cls, payload: dict[str, Any]) -> AppInstalledEvent:
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
