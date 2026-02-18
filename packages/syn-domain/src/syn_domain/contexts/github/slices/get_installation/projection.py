"""Installation projection.

Projects installation events into the Installation read model.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.github.domain.read_models.installation import (
    Installation,
    InstallationStatus,
)

if TYPE_CHECKING:
    from syn_domain.contexts.github.domain.events.AppInstalledEvent import (
        AppInstalledEvent,
    )
    from syn_domain.contexts.github.domain.events.InstallationRevokedEvent import (
        InstallationRevokedEvent,
    )
    from syn_domain.contexts.github.domain.events.InstallationSuspendedEvent import (
        InstallationSuspendedEvent,
    )
    from syn_domain.contexts.github.domain.events.TokenRefreshedEvent import (
        TokenRefreshedEvent,
    )

logger = logging.getLogger(__name__)


class InstallationProjection:
    """Projects installation events into the Installation read model.

    Maintains an in-memory cache of installations for fast lookups.
    In production, this would be backed by a database.
    """

    def __init__(self) -> None:
        """Initialize the projection."""
        self._installations: dict[str, Installation] = {}

    def handle_app_installed(self, event: AppInstalledEvent) -> Installation:
        """Handle an AppInstalled event.

        Creates a new Installation read model from the event.

        Args:
            event: The AppInstalled event.

        Returns:
            The created Installation.
        """
        # Note: DomainEvent doesn't have occurred_at - that's in EventMetadata
        # For webhook-created events, we use current time as the installation time
        installation = Installation(
            installation_id=event.installation_id,
            account_id=event.account_id,
            account_name=event.account_name,
            account_type=event.account_type,
            status=InstallationStatus.ACTIVE,
            repositories=list(event.repositories),
            permissions=dict(event.permissions),
            installed_at=datetime.now(UTC),
        )

        self._installations[event.installation_id] = installation
        logger.info(f"Projected AppInstalled: {event.installation_id} ({event.account_name})")

        return installation

    def handle_installation_revoked(self, event: InstallationRevokedEvent) -> Installation | None:
        """Handle an InstallationRevoked event.

        Marks the installation as revoked.

        Args:
            event: The InstallationRevoked event.

        Returns:
            The updated Installation, or None if not found.
        """
        installation = self._installations.get(event.installation_id)
        if installation is None:
            logger.warning(f"InstallationRevoked for unknown installation: {event.installation_id}")
            return None

        installation.status = InstallationStatus.REVOKED
        logger.info(f"Projected InstallationRevoked: {event.installation_id}")

        return installation

    def handle_token_refreshed(self, event: TokenRefreshedEvent) -> Installation | None:
        """Handle a TokenRefreshed event.

        Updates the installation's token metadata.

        Args:
            event: The TokenRefreshed event.

        Returns:
            The updated Installation, or None if not found.
        """
        installation = self._installations.get(event.installation_id)
        if installation is None:
            logger.warning(f"TokenRefreshed for unknown installation: {event.installation_id}")
            return None

        # Note: DomainEvent doesn't have occurred_at - use current time
        installation.last_token_refresh = datetime.now(UTC)
        installation.last_token_expires_at = event.expires_at
        installation.permissions = dict(event.permissions)

        logger.debug(
            f"Projected TokenRefreshed: {event.installation_id} "
            f"(expires: {event.expires_at.isoformat()})"
        )

        return installation

    def handle_installation_suspended(
        self, event: InstallationSuspendedEvent
    ) -> Installation | None:
        """Handle an InstallationSuspended event.

        Updates the installation status to suspended or active.

        Args:
            event: The InstallationSuspended event.

        Returns:
            The updated Installation, or None if not found.
        """
        installation = self._installations.get(event.installation_id)
        if installation is None:
            logger.warning(
                f"InstallationSuspended for unknown installation: {event.installation_id}"
            )
            return None

        if event.suspended:
            installation.status = InstallationStatus.SUSPENDED
            logger.info(f"Projected InstallationSuspended: {event.installation_id}")
        else:
            installation.status = InstallationStatus.ACTIVE
            logger.info(f"Projected InstallationUnsuspended: {event.installation_id}")

        return installation

    def update_repositories(
        self,
        installation_id: str,
        repos_added: list[str],
        repos_removed: list[str],
    ) -> Installation | None:
        """Update the repositories for an installation.

        Args:
            installation_id: The installation ID.
            repos_added: List of repository full names to add.
            repos_removed: List of repository full names to remove.

        Returns:
            The updated Installation, or None if not found.
        """
        installation = self._installations.get(installation_id)
        if installation is None:
            logger.warning(f"UpdateRepositories for unknown installation: {installation_id}")
            return None

        # Add new repos
        for repo in repos_added:
            if repo not in installation.repositories:
                installation.repositories.append(repo)

        # Remove repos
        for repo in repos_removed:
            if repo in installation.repositories:
                installation.repositories.remove(repo)

        logger.info(
            f"Updated repositories for {installation_id}: +{len(repos_added)} -{len(repos_removed)}"
        )

        return installation

    def get(self, installation_id: str) -> Installation | None:
        """Get an installation by ID.

        Args:
            installation_id: The installation ID.

        Returns:
            The Installation, or None if not found.
        """
        return self._installations.get(installation_id)

    def get_all_active(self) -> list[Installation]:
        """Get all active installations.

        Returns:
            List of active installations.
        """
        return [i for i in self._installations.values() if i.is_active]


# Singleton projection instance
_projection: InstallationProjection | None = None


def get_installation_projection() -> InstallationProjection:
    """Get the global installation projection instance."""
    global _projection
    if _projection is None:
        _projection = InstallationProjection()
    return _projection


def reset_installation_projection() -> None:
    """Reset the global projection (for testing)."""
    global _projection
    _projection = None
