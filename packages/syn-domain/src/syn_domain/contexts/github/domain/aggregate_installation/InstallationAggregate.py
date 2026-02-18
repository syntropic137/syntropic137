"""Installation Aggregate.

Aggregate root for GitHub App installations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syn_domain.contexts.github.domain.events.AppInstalledEvent import (
    AppInstalledEvent,
)
from syn_domain.contexts.github.domain.events.InstallationRevokedEvent import (
    InstallationRevokedEvent,
)
from syn_domain.contexts.github.domain.events.TokenRefreshedEvent import (
    TokenRefreshedEvent,
)

if TYPE_CHECKING:
    from datetime import datetime


@dataclass
class InstallationAggregate:
    """Aggregate root for a GitHub App installation.

    Manages the lifecycle of a GitHub App installation including:
    - Installation creation
    - Token refresh
    - Revocation

    Attributes:
        installation_id: GitHub installation ID.
        account_name: GitHub account login name.
        account_type: 'User' or 'Organization'.
        is_revoked: Whether the installation has been revoked.
        pending_events: Events that have been applied but not persisted.
    """

    installation_id: str
    account_name: str = ""
    account_type: str = "User"
    is_revoked: bool = False
    pending_events: list = field(default_factory=list)

    @classmethod
    def install(
        cls,
        installation_id: str,
        account_id: int,
        account_name: str,
        account_type: str,
        repositories: tuple[str, ...] = (),
        permissions: dict[str, str] | None = None,
    ) -> InstallationAggregate:
        """Create a new installation from an installation event.

        Args:
            installation_id: GitHub installation ID.
            account_id: GitHub account ID.
            account_name: GitHub account login name.
            account_type: 'User' or 'Organization'.
            repositories: Tuple of accessible repository names.
            permissions: Dict of permission name to level.

        Returns:
            New InstallationAggregate with AppInstalledEvent.
        """
        aggregate = cls(
            installation_id=installation_id,
            account_name=account_name,
            account_type=account_type,
        )

        event = AppInstalledEvent(
            installation_id=installation_id,
            account_id=account_id,
            account_name=account_name,
            account_type=account_type,
            repositories=repositories,
            permissions=permissions or {},
        )

        aggregate.pending_events.append(event)
        return aggregate

    def revoke(self) -> InstallationRevokedEvent | None:
        """Revoke this installation.

        Returns:
            InstallationRevokedEvent if not already revoked, None otherwise.
        """
        if self.is_revoked:
            return None

        self.is_revoked = True

        event = InstallationRevokedEvent(
            installation_id=self.installation_id,
            account_name=self.account_name,
        )

        self.pending_events.append(event)
        return event

    def record_token_refresh(
        self,
        token_hash: str,
        expires_at: datetime,
        permissions: dict[str, str] | None = None,
    ) -> TokenRefreshedEvent | None:
        """Record a token refresh.

        Args:
            token_hash: Hash of the refreshed token (never the raw token!).
            expires_at: When the token expires.
            permissions: Updated permissions from the token response.

        Returns:
            TokenRefreshedEvent if installation is active, None if revoked.
        """
        if self.is_revoked:
            return None

        event = TokenRefreshedEvent(
            installation_id=self.installation_id,
            token_hash=token_hash,
            expires_at=expires_at,
            permissions=permissions or {},
        )

        self.pending_events.append(event)
        return event

    def clear_pending_events(self) -> list:
        """Clear and return pending events.

        Used after events have been persisted.

        Returns:
            List of pending events that were cleared.
        """
        events = self.pending_events[:]
        self.pending_events = []
        return events

    @classmethod
    def from_events(cls, events: list) -> InstallationAggregate | None:
        """Reconstitute aggregate from event history.

        Args:
            events: List of domain events in order.

        Returns:
            InstallationAggregate with state from events, or None if no events.
        """
        if not events:
            return None

        aggregate = None

        for event in events:
            if isinstance(event, AppInstalledEvent):
                aggregate = cls(
                    installation_id=event.installation_id,
                    account_name=event.account_name,
                    account_type=event.account_type,
                )
            elif aggregate and isinstance(event, InstallationRevokedEvent):
                aggregate.is_revoked = True
            # TokenRefreshedEvent doesn't change aggregate state

        return aggregate
