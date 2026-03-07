"""Shared test fixtures for organization insight handler tests."""

from __future__ import annotations

from typing import Any

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

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        self._data.setdefault(projection, {})[key] = data

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        return self._data.get(projection, {}).get(key)

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        return list(self._data.get(projection, {}).values())


def _make_projections(
    system_id: str, system_name: str, org_id: str, repo_full_names: list[str]
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

    sys_proj = SystemProjection()
    repo_proj = RepoProjection()

    sys_proj.handle_system_created(
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
        repo_proj.handle_repo_registered(
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
        repo_proj.handle_repo_assigned_to_system(
            RepoAssignedToSystemEvent(
                repo_id=repo_id,
                system_id=system_id,
            )
        )

    return sys_proj, repo_proj
