"""Installation read model.

Represents the current state of a GitHub App installation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 - needed for runtime type annotations
from enum import StrEnum


class InstallationStatus(StrEnum):
    """Status of a GitHub App installation."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass
class Installation:
    """Read model for a GitHub App installation.

    Represents the current state of an installation, projected from events.

    Attributes:
        installation_id: GitHub installation ID.
        account_id: GitHub account ID (user or org).
        account_name: GitHub account login name.
        account_type: 'User' or 'Organization'.
        status: Current installation status.
        repositories: List of accessible repository full names.
        permissions: Dict of permission name to level.
        installed_at: When the installation was created.
        last_token_refresh: When the token was last refreshed.
        last_token_expires_at: When the current token expires.
        synced_at: When this record was last synced from the GitHub API.
    """

    installation_id: str
    account_id: int
    account_name: str
    account_type: str
    status: InstallationStatus = InstallationStatus.ACTIVE
    repositories: list[str] = field(default_factory=list)
    permissions: dict[str, str] = field(default_factory=dict)
    installed_at: datetime | None = None
    last_token_refresh: datetime | None = None
    last_token_expires_at: datetime | None = None
    synced_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Check if the installation is active."""
        return self.status == InstallationStatus.ACTIVE

    @property
    def has_contents_write(self) -> bool:
        """Check if installation has write access to repository contents.

        This permission is required for making commits.
        """
        return self.permissions.get("contents") in ("write", "admin")

    @property
    def has_pull_requests_write(self) -> bool:
        """Check if installation has write access to pull requests.

        This permission is required for creating PRs.
        """
        return self.permissions.get("pull_requests") in ("write", "admin")
