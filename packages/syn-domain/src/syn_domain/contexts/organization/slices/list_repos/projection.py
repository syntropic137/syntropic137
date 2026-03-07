"""Repo projection.

Projects repo events into RepoSummary read models.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.organization.domain.read_models.repo_summary import (
    RepoSummary,
)

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.events.RepoAssignedToSystemEvent import (
        RepoAssignedToSystemEvent,
    )
    from syn_domain.contexts.organization.domain.events.RepoRegisteredEvent import (
        RepoRegisteredEvent,
    )
    from syn_domain.contexts.organization.domain.events.RepoUnassignedFromSystemEvent import (
        RepoUnassignedFromSystemEvent,
    )

logger = logging.getLogger(__name__)


class RepoProjection:
    def __init__(self) -> None:
        self._repos: dict[str, RepoSummary] = {}

    def handle_repo_registered(self, event: RepoRegisteredEvent) -> RepoSummary:
        summary = RepoSummary(
            repo_id=event.repo_id,
            organization_id=event.organization_id,
            provider=event.provider,
            provider_repo_id=event.provider_repo_id,
            full_name=event.full_name,
            owner=event.owner,
            default_branch=event.default_branch,
            installation_id=event.installation_id,
            is_private=event.is_private,
            created_by=event.created_by,
            created_at=datetime.now(UTC),
        )
        self._repos[event.repo_id] = summary
        logger.info(f"Projected RepoRegistered: {event.repo_id} ({event.full_name})")
        return summary

    def handle_repo_assigned_to_system(
        self, event: RepoAssignedToSystemEvent
    ) -> RepoSummary | None:
        repo = self._repos.get(event.repo_id)
        if repo is None:
            logger.warning(f"RepoAssignedToSystem for unknown repo: {event.repo_id}")
            return None
        repo.system_id = event.system_id
        logger.info(f"Projected RepoAssignedToSystem: {event.repo_id} -> {event.system_id}")
        return repo

    def handle_repo_unassigned_from_system(
        self, event: RepoUnassignedFromSystemEvent
    ) -> RepoSummary | None:
        repo = self._repos.get(event.repo_id)
        if repo is None:
            logger.warning(f"RepoUnassignedFromSystem for unknown repo: {event.repo_id}")
            return None
        repo.system_id = ""
        logger.info(f"Projected RepoUnassignedFromSystem: {event.repo_id}")
        return repo

    def get(self, repo_id: str) -> RepoSummary | None:
        return self._repos.get(repo_id)

    def list_all(
        self,
        organization_id: str | None = None,
        system_id: str | None = None,
        provider: str | None = None,
        unassigned: bool = False,
    ) -> list[RepoSummary]:
        results = list(self._repos.values())
        if organization_id:
            results = [r for r in results if r.organization_id == organization_id]
        if system_id:
            results = [r for r in results if r.system_id == system_id]
        if provider:
            results = [r for r in results if r.provider == provider]
        if unassigned:
            results = [r for r in results if not r.system_id]
        return results


_projection: RepoProjection | None = None


def get_repo_projection() -> RepoProjection:
    global _projection
    if _projection is None:
        _projection = RepoProjection()
    return _projection


def reset_repo_projection() -> None:
    global _projection
    _projection = None
