"""System projection.

Projects system events into SystemSummary read models.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.organization.domain.read_models.system_summary import (
    SystemSummary,
)

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
    from syn_domain.contexts.organization.domain.events.SystemCreatedEvent import (
        SystemCreatedEvent,
    )
    from syn_domain.contexts.organization.domain.events.SystemDeletedEvent import (
        SystemDeletedEvent,
    )
    from syn_domain.contexts.organization.domain.events.SystemUpdatedEvent import (
        SystemUpdatedEvent,
    )

logger = logging.getLogger(__name__)

PROJECTION_NAME = "systems"


def _sys_to_dict(system: SystemSummary) -> dict[str, Any]:
    return {
        "system_id": system.system_id,
        "organization_id": system.organization_id,
        "name": system.name,
        "description": system.description,
        "created_by": system.created_by,
        "created_at": system.created_at.isoformat() if system.created_at else None,
        "repo_count": system.repo_count,
        "is_deleted": system.is_deleted,
    }


def _sys_from_dict(data: dict[str, Any]) -> SystemSummary:
    return SystemSummary(
        system_id=data["system_id"],
        organization_id=data["organization_id"],
        name=data["name"],
        description=data.get("description", ""),
        created_by=data.get("created_by", ""),
        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        repo_count=data.get("repo_count", 0),
        is_deleted=data.get("is_deleted", False),
    )


class SystemProjection:
    def __init__(self, store: ProjectionStoreProtocol) -> None:
        self._store = store

    async def handle_system_created(self, event: SystemCreatedEvent) -> SystemSummary:
        summary = SystemSummary(
            system_id=event.system_id,
            organization_id=event.organization_id,
            name=event.name,
            description=event.description,
            created_by=event.created_by,
            created_at=datetime.now(UTC),
        )
        await self._store.save(PROJECTION_NAME, event.system_id, _sys_to_dict(summary))
        logger.info(f"Projected SystemCreated: {event.system_id} ({event.name})")
        return summary

    async def handle_system_updated(self, event: SystemUpdatedEvent) -> SystemSummary | None:
        data = await self._store.get(PROJECTION_NAME, event.system_id)
        if data is None:
            logger.warning(f"SystemUpdated for unknown system: {event.system_id}")
            return None
        if event.name is not None:
            data["name"] = event.name
        if event.description is not None:
            data["description"] = event.description
        await self._store.save(PROJECTION_NAME, event.system_id, data)
        logger.info(f"Projected SystemUpdated: {event.system_id}")
        return _sys_from_dict(data)

    async def handle_system_deleted(self, event: SystemDeletedEvent) -> SystemSummary | None:
        data = await self._store.get(PROJECTION_NAME, event.system_id)
        if data is None:
            logger.warning(f"SystemDeleted for unknown system: {event.system_id}")
            return None
        data["is_deleted"] = True
        await self._store.save(PROJECTION_NAME, event.system_id, data)
        logger.info(f"Projected SystemDeleted: {event.system_id}")
        return _sys_from_dict(data)

    async def get(self, system_id: str) -> SystemSummary | None:
        data = await self._store.get(PROJECTION_NAME, system_id)
        return _sys_from_dict(data) if data else None

    async def list_all(
        self,
        organization_id: str | None = None,
        include_deleted: bool = False,
    ) -> list[SystemSummary]:
        records = await self._store.get_all(PROJECTION_NAME)
        results = [_sys_from_dict(r) for r in records]
        if organization_id:
            results = [s for s in results if s.organization_id == organization_id]
        if not include_deleted:
            results = [s for s in results if not s.is_deleted]
        return results

    async def increment_repo_count(self, system_id: str, delta: int = 1) -> None:
        data = await self._store.get(PROJECTION_NAME, system_id)
        if data:
            data["repo_count"] = data.get("repo_count", 0) + delta
            await self._store.save(PROJECTION_NAME, system_id, data)

    async def clear_all_data(self) -> None:
        """Clear all projection data (for rebuild)."""
        records = await self._store.get_all(PROJECTION_NAME)
        for record in records:
            system_id = record.get("system_id")
            if system_id:
                await self._store.delete(PROJECTION_NAME, system_id)

    # ------------------------------------------------------------------
    # Dict-based adapters — called by ProjectionManager dispatch
    # ------------------------------------------------------------------

    async def on_system_created(self, event: dict[str, Any]) -> None:
        """Handle SystemCreated event dict from manager dispatch."""
        system_id = str(event.get("system_id", ""))
        if not system_id:
            return
        summary = SystemSummary(
            system_id=system_id,
            organization_id=str(event.get("organization_id", "")),
            name=str(event.get("name", "")),
            description=str(event.get("description", "")),
            created_by=str(event.get("created_by", "")),
            created_at=datetime.now(UTC),
        )
        await self._store.save(PROJECTION_NAME, system_id, _sys_to_dict(summary))
        logger.info(f"Projected SystemCreated: {system_id}")

    async def on_system_updated(self, event: dict[str, Any]) -> None:
        """Handle SystemUpdated event dict from manager dispatch."""
        system_id = str(event.get("system_id", ""))
        if not system_id:
            return
        data = await self._store.get(PROJECTION_NAME, system_id)
        if data is None:
            logger.warning(f"SystemUpdated for unknown system: {system_id}")
            return
        if event.get("name") is not None:
            data["name"] = event["name"]
        if event.get("description") is not None:
            data["description"] = event["description"]
        await self._store.save(PROJECTION_NAME, system_id, data)
        logger.info(f"Projected SystemUpdated: {system_id}")

    async def on_system_deleted(self, event: dict[str, Any]) -> None:
        """Handle SystemDeleted event dict from manager dispatch."""
        system_id = str(event.get("system_id", ""))
        if not system_id:
            return
        data = await self._store.get(PROJECTION_NAME, system_id)
        if data is None:
            logger.warning(f"SystemDeleted for unknown system: {system_id}")
            return
        data["is_deleted"] = True
        await self._store.save(PROJECTION_NAME, system_id, data)
        logger.info(f"Projected SystemDeleted: {system_id}")

    async def on_repo_registered_increment(self, event: dict[str, Any]) -> None:
        """Increment repo_count when a repo is assigned to this system at registration."""
        system_id = str(event.get("system_id", ""))
        if system_id:
            await self.increment_repo_count(system_id)

    # Canonical name for coordinator dispatch (bare event type: RepoRegistered)
    on_repo_registered = on_repo_registered_increment

    async def on_repo_assigned_increment(self, event: dict[str, Any]) -> None:
        """Increment repo_count when a repo is assigned to this system."""
        system_id = str(event.get("system_id", ""))
        if system_id:
            await self.increment_repo_count(system_id)

    # Canonical name for coordinator dispatch (bare event type: RepoAssignedToSystem)
    on_repo_assigned_to_system = on_repo_assigned_increment

    async def on_repo_unassigned_decrement(self, event: dict[str, Any]) -> None:
        """Decrement repo_count when a repo is unassigned from this system."""
        system_id = str(event.get("old_system_id") or event.get("system_id", ""))
        if system_id:
            await self.increment_repo_count(system_id, delta=-1)

    # Canonical name for coordinator dispatch (bare event type: RepoUnassignedFromSystem)
    on_repo_unassigned_from_system = on_repo_unassigned_decrement


_projection: SystemProjection | None = None


def get_system_projection() -> SystemProjection:
    global _projection
    if _projection is None:
        from syn_adapters.projection_stores import get_projection_store

        _projection = SystemProjection(store=get_projection_store())
    return _projection


def reset_system_projection() -> None:
    global _projection
    _projection = None
