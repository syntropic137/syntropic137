"""Organization projection.

Projects organization events into OrganizationSummary read models.
Shared between list_organizations and get_organization slices.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.organization.domain.read_models.organization_summary import (
    OrganizationSummary,
)

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
    from syn_domain.contexts.organization.domain.events.OrganizationCreatedEvent import (
        OrganizationCreatedEvent,
    )
    from syn_domain.contexts.organization.domain.events.OrganizationDeletedEvent import (
        OrganizationDeletedEvent,
    )
    from syn_domain.contexts.organization.domain.events.OrganizationUpdatedEvent import (
        OrganizationUpdatedEvent,
    )

logger = logging.getLogger(__name__)

PROJECTION_NAME = "organizations"


def _org_to_dict(org: OrganizationSummary) -> dict[str, Any]:
    return {
        "organization_id": org.organization_id,
        "name": org.name,
        "slug": org.slug,
        "created_by": org.created_by,
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "system_count": org.system_count,
        "repo_count": org.repo_count,
        "is_deleted": org.is_deleted,
    }


def _org_from_dict(data: dict[str, Any]) -> OrganizationSummary:
    return OrganizationSummary(
        organization_id=data["organization_id"],
        name=data["name"],
        slug=data["slug"],
        created_by=data.get("created_by", ""),
        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        system_count=data.get("system_count", 0),
        repo_count=data.get("repo_count", 0),
        is_deleted=data.get("is_deleted", False),
    )


class OrganizationProjection:
    def __init__(self, store: ProjectionStoreProtocol) -> None:
        self._store = store

    async def handle_organization_created(
        self, event: OrganizationCreatedEvent
    ) -> OrganizationSummary:
        await self.on_organization_created(
            {
                "organization_id": event.organization_id,
                "name": event.name,
                "slug": event.slug,
                "created_by": event.created_by,
            }
        )
        data = await self._store.get(PROJECTION_NAME, event.organization_id)
        return (
            _org_from_dict(data)
            if data
            else OrganizationSummary(
                organization_id=event.organization_id, name=event.name, slug=event.slug
            )
        )

    async def handle_organization_updated(
        self, event: OrganizationUpdatedEvent
    ) -> OrganizationSummary | None:
        await self.on_organization_updated(
            {
                "organization_id": event.organization_id,
                "name": event.name,
                "slug": event.slug,
            }
        )
        data = await self._store.get(PROJECTION_NAME, event.organization_id)
        return _org_from_dict(data) if data else None

    async def handle_organization_deleted(
        self, event: OrganizationDeletedEvent
    ) -> OrganizationSummary | None:
        await self.on_organization_deleted({"organization_id": event.organization_id})
        data = await self._store.get(PROJECTION_NAME, event.organization_id)
        return _org_from_dict(data) if data else None

    async def get(self, organization_id: str) -> OrganizationSummary | None:
        data = await self._store.get(PROJECTION_NAME, organization_id)
        return _org_from_dict(data) if data else None

    async def list_all(self, include_deleted: bool = False) -> list[OrganizationSummary]:
        records = await self._store.get_all(PROJECTION_NAME)
        results = [_org_from_dict(r) for r in records]
        if not include_deleted:
            results = [o for o in results if not o.is_deleted]
        return results

    async def increment_system_count(self, organization_id: str, delta: int = 1) -> None:
        data = await self._store.get(PROJECTION_NAME, organization_id)
        if data:
            data["system_count"] = data.get("system_count", 0) + delta
            await self._store.save(PROJECTION_NAME, organization_id, data)

    async def increment_repo_count(self, organization_id: str, delta: int = 1) -> None:
        data = await self._store.get(PROJECTION_NAME, organization_id)
        if data:
            data["repo_count"] = data.get("repo_count", 0) + delta
            await self._store.save(PROJECTION_NAME, organization_id, data)

    async def clear_all_data(self) -> None:
        """Clear all projection data (for rebuild)."""
        records = await self._store.get_all(PROJECTION_NAME)
        for record in records:
            org_id = record.get("organization_id")
            if org_id:
                await self._store.delete(PROJECTION_NAME, org_id)

    # ------------------------------------------------------------------
    # Dict-based adapters — called by ProjectionManager dispatch
    # ------------------------------------------------------------------

    async def on_organization_created(self, event: dict[str, Any]) -> None:
        """Handle OrganizationCreated event dict from manager dispatch."""
        org_id = str(event.get("organization_id", ""))
        if not org_id:
            return
        summary = OrganizationSummary(
            organization_id=org_id,
            name=str(event.get("name", "")),
            slug=str(event.get("slug", "")),
            created_by=str(event.get("created_by", "")),
            created_at=datetime.now(UTC),
        )
        await self._store.save(PROJECTION_NAME, org_id, _org_to_dict(summary))
        logger.info(f"Projected OrganizationCreated: {org_id}")

    async def on_organization_updated(self, event: dict[str, Any]) -> None:
        """Handle OrganizationUpdated event dict from manager dispatch."""
        org_id = str(event.get("organization_id", ""))
        if not org_id:
            return
        data = await self._store.get(PROJECTION_NAME, org_id)
        if data is None:
            logger.warning(f"OrganizationUpdated for unknown org: {org_id}")
            return
        if event.get("name") is not None:
            data["name"] = event["name"]
        if event.get("slug") is not None:
            data["slug"] = event["slug"]
        await self._store.save(PROJECTION_NAME, org_id, data)
        logger.info(f"Projected OrganizationUpdated: {org_id}")

    async def on_organization_deleted(self, event: dict[str, Any]) -> None:
        """Handle OrganizationDeleted event dict from manager dispatch."""
        org_id = str(event.get("organization_id", ""))
        if not org_id:
            return
        data = await self._store.get(PROJECTION_NAME, org_id)
        if data is None:
            logger.warning(f"OrganizationDeleted for unknown org: {org_id}")
            return
        data["is_deleted"] = True
        await self._store.save(PROJECTION_NAME, org_id, data)
        logger.info(f"Projected OrganizationDeleted: {org_id}")

    async def on_system_created_increment(self, event: dict[str, Any]) -> None:
        """Increment system_count when a system is created under this org."""
        org_id = str(event.get("organization_id", ""))
        if org_id:
            await self.increment_system_count(org_id)

    # Canonical name for coordinator dispatch (bare event type: SystemCreated)
    on_system_created = on_system_created_increment

    async def on_system_deleted_decrement(self, event: dict[str, Any]) -> None:
        """Decrement system_count when a system is deleted."""
        org_id = str(event.get("organization_id", ""))
        if org_id:
            await self.increment_system_count(org_id, delta=-1)

    # Canonical name for coordinator dispatch (bare event type: SystemDeleted)
    on_system_deleted = on_system_deleted_decrement

    async def on_repo_registered_increment(self, event: dict[str, Any]) -> None:
        """Increment repo_count when a repo is registered under this org."""
        org_id = str(event.get("organization_id", ""))
        if org_id:
            await self.increment_repo_count(org_id)

    # Canonical name for coordinator dispatch (bare event type: RepoRegistered)
    on_repo_registered = on_repo_registered_increment

    async def on_repo_deregistered_decrement(self, event: dict[str, Any]) -> None:
        """Decrement repo_count when a repo is deregistered."""
        org_id = str(event.get("organization_id", ""))
        if org_id:
            await self.increment_repo_count(org_id, delta=-1)


_projection: OrganizationProjection | None = None


def get_organization_projection() -> OrganizationProjection:
    global _projection
    if _projection is None:
        from syn_adapters.projection_stores import get_projection_store

        _projection = OrganizationProjection(store=get_projection_store())
    return _projection


def reset_organization_projection() -> None:
    global _projection
    _projection = None
