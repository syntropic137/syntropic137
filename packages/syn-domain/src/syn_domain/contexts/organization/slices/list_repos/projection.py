"""Repo projection.

Projects repo events into RepoSummary read models.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.organization.domain.read_models.repo_summary import (
    RepoSummary,
)

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
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

PROJECTION_NAME = "repos"


def _repo_to_dict(repo: RepoSummary) -> dict[str, Any]:
    return {
        "repo_id": repo.repo_id,
        "organization_id": repo.organization_id,
        "system_id": repo.system_id,
        "provider": repo.provider,
        "provider_repo_id": repo.provider_repo_id,
        "full_name": repo.full_name,
        "owner": repo.owner,
        "default_branch": repo.default_branch,
        "installation_id": repo.installation_id,
        "is_private": repo.is_private,
        "created_by": repo.created_by,
        "created_at": repo.created_at.isoformat() if repo.created_at else None,
    }


def _repo_from_dict(data: dict[str, Any]) -> RepoSummary:
    return RepoSummary(
        repo_id=data["repo_id"],
        organization_id=data["organization_id"],
        system_id=data.get("system_id", ""),
        provider=data.get("provider", "github"),
        provider_repo_id=data.get("provider_repo_id", ""),
        full_name=data.get("full_name", ""),
        owner=data.get("owner", ""),
        default_branch=data.get("default_branch", "main"),
        installation_id=data.get("installation_id", ""),
        is_private=data.get("is_private", False),
        created_by=data.get("created_by", ""),
        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
    )


class RepoProjection:
    def __init__(self, store: ProjectionStoreProtocol) -> None:
        self._store = store

    async def handle_repo_registered(self, event: RepoRegisteredEvent) -> RepoSummary:
        await self.on_repo_registered(
            {
                "repo_id": event.repo_id,
                "organization_id": event.organization_id,
                "provider": event.provider,
                "provider_repo_id": event.provider_repo_id,
                "full_name": event.full_name,
                "owner": event.owner,
                "default_branch": event.default_branch,
                "installation_id": event.installation_id,
                "is_private": event.is_private,
                "created_by": event.created_by,
            }
        )
        data = await self._store.get(PROJECTION_NAME, event.repo_id)
        return (
            _repo_from_dict(data)
            if data
            else RepoSummary(
                repo_id=event.repo_id,
                organization_id=event.organization_id,
                full_name=event.full_name,
            )
        )

    async def handle_repo_assigned_to_system(
        self, event: RepoAssignedToSystemEvent
    ) -> RepoSummary | None:
        await self.on_repo_assigned_to_system(
            {
                "repo_id": event.repo_id,
                "system_id": event.system_id,
            }
        )
        data = await self._store.get(PROJECTION_NAME, event.repo_id)
        return _repo_from_dict(data) if data else None

    async def handle_repo_unassigned_from_system(
        self, event: RepoUnassignedFromSystemEvent
    ) -> RepoSummary | None:
        await self.on_repo_unassigned_from_system({"repo_id": event.repo_id})
        data = await self._store.get(PROJECTION_NAME, event.repo_id)
        return _repo_from_dict(data) if data else None

    async def get(self, repo_id: str) -> RepoSummary | None:
        data = await self._store.get(PROJECTION_NAME, repo_id)
        return _repo_from_dict(data) if data else None

    @staticmethod
    def _matches_filters(
        repo: RepoSummary,
        organization_id: str | None,
        system_id: str | None,
        provider: str | None,
        unassigned: bool,
    ) -> bool:
        """Check if a repo matches all active filter criteria."""
        if organization_id and repo.organization_id != organization_id:
            return False
        if system_id and repo.system_id != system_id:
            return False
        if provider and repo.provider != provider:
            return False
        if unassigned and repo.system_id:
            return False
        return True

    async def list_all(
        self,
        organization_id: str | None = None,
        system_id: str | None = None,
        provider: str | None = None,
        unassigned: bool = False,
    ) -> list[RepoSummary]:
        records = await self._store.get_all(PROJECTION_NAME)
        repos = [_repo_from_dict(r) for r in records]
        return [
            r
            for r in repos
            if self._matches_filters(r, organization_id, system_id, provider, unassigned)
        ]

    async def clear_all_data(self) -> None:
        """Clear all projection data (for rebuild)."""
        records = await self._store.get_all(PROJECTION_NAME)
        for record in records:
            repo_id = record.get("repo_id")
            if repo_id:
                await self._store.delete(PROJECTION_NAME, repo_id)

    # ------------------------------------------------------------------
    # Dict-based adapters — called by ProjectionManager dispatch
    # ------------------------------------------------------------------

    async def on_repo_registered(self, event: dict[str, Any]) -> None:
        """Handle RepoRegistered event dict from manager dispatch."""
        repo_id = str(event.get("repo_id", ""))
        if not repo_id:
            return
        summary = RepoSummary(
            repo_id=repo_id,
            organization_id=str(event.get("organization_id", "")),
            system_id=str(event.get("system_id") or ""),
            provider=str(event.get("provider", "github")),
            provider_repo_id=str(event.get("provider_repo_id", "")),
            full_name=str(event.get("full_name", "")),
            owner=str(event.get("owner", "")),
            default_branch=str(event.get("default_branch", "main")),
            installation_id=str(event.get("installation_id", "")),
            is_private=bool(event.get("is_private", False)),
            created_by=str(event.get("created_by", "")),
            created_at=datetime.now(UTC),
        )
        await self._store.save(PROJECTION_NAME, repo_id, _repo_to_dict(summary))
        logger.info(f"Projected RepoRegistered: {repo_id}")

    async def on_repo_assigned_to_system(self, event: dict[str, Any]) -> None:
        """Handle RepoAssignedToSystem event dict from manager dispatch."""
        repo_id = str(event.get("repo_id", ""))
        if not repo_id:
            return
        data = await self._store.get(PROJECTION_NAME, repo_id)
        if data is None:
            logger.warning(f"RepoAssignedToSystem for unknown repo: {repo_id}")
            return
        data["system_id"] = str(event.get("system_id", ""))
        await self._store.save(PROJECTION_NAME, repo_id, data)
        logger.info(f"Projected RepoAssignedToSystem: {repo_id}")

    async def on_repo_unassigned_from_system(self, event: dict[str, Any]) -> None:
        """Handle RepoUnassignedFromSystem event dict from manager dispatch."""
        repo_id = str(event.get("repo_id", ""))
        if not repo_id:
            return
        data = await self._store.get(PROJECTION_NAME, repo_id)
        if data is None:
            logger.warning(f"RepoUnassignedFromSystem for unknown repo: {repo_id}")
            return
        data["system_id"] = ""
        await self._store.save(PROJECTION_NAME, repo_id, data)
        logger.info(f"Projected RepoUnassignedFromSystem: {repo_id}")


_projection: RepoProjection | None = None


def get_repo_projection() -> RepoProjection:
    global _projection
    if _projection is None:
        from syn_adapters.projection_stores import get_projection_store

        _projection = RepoProjection(store=get_projection_store())
    return _projection


def reset_repo_projection() -> None:
    global _projection
    _projection = None
