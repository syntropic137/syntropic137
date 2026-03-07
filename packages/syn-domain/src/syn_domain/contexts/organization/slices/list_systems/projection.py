"""System projection.

Projects system events into SystemSummary read models.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.organization.domain.read_models.system_summary import (
    SystemSummary,
)

if TYPE_CHECKING:
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


class SystemProjection:
    def __init__(self) -> None:
        self._systems: dict[str, SystemSummary] = {}

    def handle_system_created(self, event: SystemCreatedEvent) -> SystemSummary:
        summary = SystemSummary(
            system_id=event.system_id,
            organization_id=event.organization_id,
            name=event.name,
            description=event.description,
            created_by=event.created_by,
            created_at=datetime.now(UTC),
        )
        self._systems[event.system_id] = summary
        logger.info(f"Projected SystemCreated: {event.system_id} ({event.name})")
        return summary

    def handle_system_updated(self, event: SystemUpdatedEvent) -> SystemSummary | None:
        system = self._systems.get(event.system_id)
        if system is None:
            logger.warning(f"SystemUpdated for unknown system: {event.system_id}")
            return None
        if event.name is not None:
            system.name = event.name
        if event.description is not None:
            system.description = event.description
        logger.info(f"Projected SystemUpdated: {event.system_id}")
        return system

    def handle_system_deleted(self, event: SystemDeletedEvent) -> SystemSummary | None:
        system = self._systems.get(event.system_id)
        if system is None:
            logger.warning(f"SystemDeleted for unknown system: {event.system_id}")
            return None
        system.is_deleted = True
        logger.info(f"Projected SystemDeleted: {event.system_id}")
        return system

    def get(self, system_id: str) -> SystemSummary | None:
        return self._systems.get(system_id)

    def list_all(
        self,
        organization_id: str | None = None,
        include_deleted: bool = False,
    ) -> list[SystemSummary]:
        results = list(self._systems.values())
        if organization_id:
            results = [s for s in results if s.organization_id == organization_id]
        if not include_deleted:
            results = [s for s in results if not s.is_deleted]
        return results

    def increment_repo_count(self, system_id: str, delta: int = 1) -> None:
        system = self._systems.get(system_id)
        if system:
            system.repo_count += delta


_projection: SystemProjection | None = None


def get_system_projection() -> SystemProjection:
    global _projection
    if _projection is None:
        _projection = SystemProjection()
    return _projection


def reset_system_projection() -> None:
    global _projection
    _projection = None
