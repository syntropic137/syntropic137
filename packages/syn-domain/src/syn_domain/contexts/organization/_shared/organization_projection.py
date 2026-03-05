"""Organization projection.

Projects organization events into OrganizationSummary read models.
Shared between list_organizations and get_organization slices.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.organization.domain.read_models.organization_summary import (
    OrganizationSummary,
)

if TYPE_CHECKING:
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


class OrganizationProjection:
    def __init__(self) -> None:
        self._orgs: dict[str, OrganizationSummary] = {}

    def handle_organization_created(
        self, event: OrganizationCreatedEvent
    ) -> OrganizationSummary:
        summary = OrganizationSummary(
            organization_id=event.organization_id,
            name=event.name,
            slug=event.slug,
            created_by=event.created_by,
            created_at=datetime.now(UTC),
        )
        self._orgs[event.organization_id] = summary
        logger.info(
            f"Projected OrganizationCreated: {event.organization_id} ({event.name})"
        )
        return summary

    def handle_organization_updated(
        self, event: OrganizationUpdatedEvent
    ) -> OrganizationSummary | None:
        org = self._orgs.get(event.organization_id)
        if org is None:
            logger.warning(
                f"OrganizationUpdated for unknown org: {event.organization_id}"
            )
            return None
        if event.name is not None:
            org.name = event.name
        if event.slug is not None:
            org.slug = event.slug
        logger.info(f"Projected OrganizationUpdated: {event.organization_id}")
        return org

    def handle_organization_deleted(
        self, event: OrganizationDeletedEvent
    ) -> OrganizationSummary | None:
        org = self._orgs.get(event.organization_id)
        if org is None:
            logger.warning(
                f"OrganizationDeleted for unknown org: {event.organization_id}"
            )
            return None
        org.is_deleted = True
        logger.info(f"Projected OrganizationDeleted: {event.organization_id}")
        return org

    def get(self, organization_id: str) -> OrganizationSummary | None:
        return self._orgs.get(organization_id)

    def list_all(self, include_deleted: bool = False) -> list[OrganizationSummary]:
        results = list(self._orgs.values())
        if not include_deleted:
            results = [o for o in results if not o.is_deleted]
        return results

    def increment_system_count(self, organization_id: str, delta: int = 1) -> None:
        org = self._orgs.get(organization_id)
        if org:
            org.system_count += delta

    def increment_repo_count(self, organization_id: str, delta: int = 1) -> None:
        org = self._orgs.get(organization_id)
        if org:
            org.repo_count += delta


_projection: OrganizationProjection | None = None


def get_organization_projection() -> OrganizationProjection:
    global _projection
    if _projection is None:
        _projection = OrganizationProjection()
    return _projection


def reset_organization_projection() -> None:
    global _projection
    _projection = None
