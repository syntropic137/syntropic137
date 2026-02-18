"""Value objects for GitHub context.

Immutable domain primitives that encapsulate GitHub App concepts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class InstallationId:
    """GitHub App installation identifier.

    Represents a unique installation of the GitHub App in an organization
    or user account. Each installation has access to specific repositories.

    Attributes:
        value: The numeric installation ID from GitHub.
    """

    value: str

    def __post_init__(self) -> None:
        """Validate the installation ID."""
        if not self.value:
            raise ValueError("Installation ID cannot be empty")
        if not self.value.isdigit():
            raise ValueError(f"Installation ID must be numeric, got: {self.value}")

    def __str__(self) -> str:
        """Return the string representation."""
        return self.value


@dataclass(frozen=True)
class InstallationToken:
    """GitHub App installation access token.

    Short-lived token for authenticating as the GitHub App installation.
    These tokens expire after 1 hour and should never be stored long-term.

    Attributes:
        token: The access token string (sensitive - never log!).
        expires_at: When the token expires (UTC).
    """

    token: str
    expires_at: datetime

    def __post_init__(self) -> None:
        """Validate the token."""
        if not self.token:
            raise ValueError("Token cannot be empty")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")

    @property
    def is_expired(self) -> bool:
        """Check if the token has expired.

        Returns:
            True if the token has expired or will expire within 60 seconds.
        """
        from datetime import timedelta

        # Add 60 second buffer to avoid using tokens about to expire
        buffer = timedelta(seconds=60)
        return datetime.now(UTC) >= self.expires_at - buffer

    @property
    def is_expiring_soon(self) -> bool:
        """Check if the token will expire within 5 minutes.

        Useful for proactive refresh.

        Returns:
            True if token expires within 5 minutes.
        """
        from datetime import timedelta

        threshold = datetime.now(UTC) + timedelta(minutes=5)
        return threshold >= self.expires_at

    @property
    def token_hash(self) -> str:
        """Get a hash of the token for logging/auditing.

        Never log the actual token - use this hash instead.

        Returns:
            SHA-256 hash of the token (first 12 chars).
        """
        return hashlib.sha256(self.token.encode()).hexdigest()[:12]

    def __repr__(self) -> str:
        """Return a safe representation without exposing the token."""
        return (
            f"InstallationToken(hash={self.token_hash}, expires_at={self.expires_at.isoformat()})"
        )


@dataclass(frozen=True)
class RepositoryPermission:
    """Permission granted to the GitHub App for a repository.

    Attributes:
        name: Permission name (e.g., 'contents', 'pull_requests').
        level: Permission level ('read', 'write', 'admin').
    """

    name: str
    level: str

    def __post_init__(self) -> None:
        """Validate the permission."""
        valid_levels = {"read", "write", "admin"}
        if self.level not in valid_levels:
            raise ValueError(
                f"Invalid permission level: {self.level}. Must be one of: {valid_levels}"
            )


@dataclass(frozen=True)
class GitHubAccount:
    """GitHub account (user or organization).

    Attributes:
        id: GitHub account ID.
        login: GitHub username/org name.
        account_type: 'User' or 'Organization'.
    """

    id: int
    login: str
    account_type: str

    def __post_init__(self) -> None:
        """Validate the account."""
        valid_types = {"User", "Organization"}
        if self.account_type not in valid_types:
            raise ValueError(
                f"Invalid account type: {self.account_type}. Must be one of: {valid_types}"
            )
