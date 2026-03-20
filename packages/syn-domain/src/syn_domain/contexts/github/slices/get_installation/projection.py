"""Installation projection.

Projects installation events into the Installation read model.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.github._shared.projection_names import INSTALLATIONS
from syn_domain.contexts.github.domain.read_models.installation import (
    Installation,
    InstallationStatus,
)

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
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

PROJECTION_NAME = INSTALLATIONS


def _inst_to_dict(inst: Installation) -> dict[str, Any]:
    return {
        "installation_id": inst.installation_id,
        "account_id": inst.account_id,
        "account_name": inst.account_name,
        "account_type": inst.account_type,
        "status": inst.status.value,
        "repositories": inst.repositories,
        "permissions": inst.permissions,
        "installed_at": inst.installed_at.isoformat() if inst.installed_at else None,
        "last_token_refresh": inst.last_token_refresh.isoformat()
        if inst.last_token_refresh
        else None,
        "last_token_expires_at": inst.last_token_expires_at.isoformat()
        if inst.last_token_expires_at
        else None,
    }


def _inst_from_dict(data: dict[str, Any]) -> Installation:
    return Installation(
        installation_id=data["installation_id"],
        account_id=data["account_id"],
        account_name=data["account_name"],
        account_type=data["account_type"],
        status=InstallationStatus(data["status"]),
        repositories=data.get("repositories", []),
        permissions=data.get("permissions", {}),
        installed_at=datetime.fromisoformat(data["installed_at"])
        if data.get("installed_at")
        else None,
        last_token_refresh=datetime.fromisoformat(data["last_token_refresh"])
        if data.get("last_token_refresh")
        else None,
        last_token_expires_at=datetime.fromisoformat(data["last_token_expires_at"])
        if data.get("last_token_expires_at")
        else None,
    )


class InstallationProjection:
    """Projects installation events into the Installation read model."""

    def __init__(self, store: ProjectionStoreProtocol) -> None:
        """Initialize the projection."""
        self._store = store

    async def handle_app_installed(self, event: AppInstalledEvent) -> Installation:
        """Handle an AppInstalled event."""
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
        await self._store.save(PROJECTION_NAME, event.installation_id, _inst_to_dict(installation))
        logger.info(f"Projected AppInstalled: {event.installation_id} ({event.account_name})")
        return installation

    async def handle_installation_revoked(
        self, event: InstallationRevokedEvent
    ) -> Installation | None:
        """Handle an InstallationRevoked event."""
        data = await self._store.get(PROJECTION_NAME, event.installation_id)
        if data is None:
            logger.warning(f"InstallationRevoked for unknown installation: {event.installation_id}")
            return None
        data["status"] = InstallationStatus.REVOKED.value
        await self._store.save(PROJECTION_NAME, event.installation_id, data)
        logger.info(f"Projected InstallationRevoked: {event.installation_id}")
        return _inst_from_dict(data)

    async def handle_token_refreshed(self, event: TokenRefreshedEvent) -> Installation | None:
        """Handle a TokenRefreshed event."""
        data = await self._store.get(PROJECTION_NAME, event.installation_id)
        if data is None:
            logger.warning(f"TokenRefreshed for unknown installation: {event.installation_id}")
            return None
        # Note: DomainEvent doesn't have occurred_at - use current time
        data["last_token_refresh"] = datetime.now(UTC).isoformat()
        data["last_token_expires_at"] = event.expires_at.isoformat()
        data["permissions"] = dict(event.permissions)
        await self._store.save(PROJECTION_NAME, event.installation_id, data)
        logger.debug(
            f"Projected TokenRefreshed: {event.installation_id} "
            f"(expires: {event.expires_at.isoformat()})"
        )
        return _inst_from_dict(data)

    async def handle_installation_suspended(
        self, event: InstallationSuspendedEvent
    ) -> Installation | None:
        """Handle an InstallationSuspended event."""
        data = await self._store.get(PROJECTION_NAME, event.installation_id)
        if data is None:
            logger.warning(
                f"InstallationSuspended for unknown installation: {event.installation_id}"
            )
            return None
        if event.suspended:
            data["status"] = InstallationStatus.SUSPENDED.value
            logger.info(f"Projected InstallationSuspended: {event.installation_id}")
        else:
            data["status"] = InstallationStatus.ACTIVE.value
            logger.info(f"Projected InstallationUnsuspended: {event.installation_id}")
        await self._store.save(PROJECTION_NAME, event.installation_id, data)
        return _inst_from_dict(data)

    async def update_repositories(
        self,
        installation_id: str,
        repos_added: list[str],
        repos_removed: list[str],
    ) -> Installation | None:
        """Update the repositories for an installation."""
        data = await self._store.get(PROJECTION_NAME, installation_id)
        if data is None:
            logger.warning(f"UpdateRepositories for unknown installation: {installation_id}")
            return None
        repos: list[str] = data.get("repositories", [])
        for repo in repos_added:
            if repo not in repos:
                repos.append(repo)
        for repo in repos_removed:
            if repo in repos:
                repos.remove(repo)
        data["repositories"] = repos
        await self._store.save(PROJECTION_NAME, installation_id, data)
        logger.info(
            f"Updated repositories for {installation_id}: +{len(repos_added)} -{len(repos_removed)}"
        )
        return _inst_from_dict(data)

    async def get(self, installation_id: str) -> Installation | None:
        """Get an installation by ID."""
        data = await self._store.get(PROJECTION_NAME, installation_id)
        return _inst_from_dict(data) if data else None

    async def get_all_active(self) -> list[Installation]:
        """Get all active installations."""
        records = await self._store.get_all(PROJECTION_NAME)
        return [
            _inst_from_dict(r)
            for r in records
            if r.get("status") == InstallationStatus.ACTIVE.value
        ]

    async def clear_all_data(self) -> None:
        """Clear all projection data (for rebuild)."""
        records = await self._store.get_all(PROJECTION_NAME)
        for record in records:
            inst_id = record.get("installation_id")
            if inst_id:
                await self._store.delete(PROJECTION_NAME, inst_id)


# Singleton projection instance
_projection: InstallationProjection | None = None


def get_installation_projection() -> InstallationProjection:
    """Get the global installation projection instance."""
    global _projection
    if _projection is None:
        from syn_adapters.projection_stores import get_projection_store

        _projection = InstallationProjection(store=get_projection_store())
    return _projection


def reset_installation_projection() -> None:
    """Reset the global projection (for testing)."""
    global _projection
    _projection = None
