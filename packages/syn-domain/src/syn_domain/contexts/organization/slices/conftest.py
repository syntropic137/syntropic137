"""Shared test fixtures for organization insight handler tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)
from syn_domain.contexts.organization.slices.list_systems.projection import (
    SystemProjection,
)


class FakeProjectionStore:
    """In-memory projection store for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._positions: dict[str, int] = {}

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        self._data.setdefault(projection, {})[key] = data

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        return self._data.get(projection, {}).get(key)

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        return list(self._data.get(projection, {}).values())

    async def delete(self, projection: str, key: str) -> None:
        self._data.get(projection, {}).pop(key, None)

    async def query(
        self,
        projection: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,  # noqa: ARG002
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        records = list(self._data.get(projection, {}).values())
        if filters:
            records = [r for r in records if all(r.get(k) == v for k, v in filters.items())]
        if offset:
            records = records[offset:]
        if limit is not None:
            records = records[:limit]
        return records

    async def get_position(self, projection: str) -> int | None:
        return self._positions.get(projection)

    async def set_position(self, projection: str, position: int) -> None:
        self._positions[projection] = position

    async def get_last_updated(self, projection: str) -> datetime | None:  # noqa: ARG002
        return None


async def _make_projections(
    system_id: str,
    system_name: str,
    org_id: str,
    repo_full_names: list[str],
    store: FakeProjectionStore | None = None,
) -> tuple[SystemProjection, RepoProjection]:
    """Create test projections with a system and its repos."""
    from syn_domain.contexts.organization.domain.events.RepoAssignedToSystemEvent import (
        RepoAssignedToSystemEvent,
    )
    from syn_domain.contexts.organization.domain.events.RepoRegisteredEvent import (
        RepoRegisteredEvent,
    )
    from syn_domain.contexts.organization.domain.events.SystemCreatedEvent import (
        SystemCreatedEvent,
    )

    if store is None:
        store = FakeProjectionStore()

    sys_proj = SystemProjection(store=store)
    repo_proj = RepoProjection(store=store)

    await sys_proj.handle_system_created(
        SystemCreatedEvent(
            system_id=system_id,
            organization_id=org_id,
            name=system_name,
            description="",
            created_by="test",
        )
    )

    for i, name in enumerate(repo_full_names):
        repo_id = f"repo-{i}"
        owner = name.split("/")[0] if "/" in name else ""
        await repo_proj.handle_repo_registered(
            RepoRegisteredEvent(
                repo_id=repo_id,
                organization_id=org_id,
                provider="github",
                provider_repo_id="",
                full_name=name,
                owner=owner,
                default_branch="main",
                installation_id="",
                is_private=False,
                created_by="test",
            )
        )
        await repo_proj.handle_repo_assigned_to_system(
            RepoAssignedToSystemEvent(
                repo_id=repo_id,
                system_id=system_id,
            )
        )

    return sys_proj, repo_proj
