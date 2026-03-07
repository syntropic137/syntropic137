"""Tests for GetSystemStatusHandler."""

from __future__ import annotations

from typing import Any

import pytest

from syn_domain.contexts.organization.domain.queries.get_system_status import (
    GetSystemStatusQuery,
)
from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)
from syn_domain.contexts.organization.slices.list_systems.projection import (
    SystemProjection,
)
from syn_domain.contexts.organization.slices.system_status.handler import (
    GetSystemStatusHandler,
)


class FakeProjectionStore:
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


@pytest.mark.unit
class TestGetSystemStatusHandler:
    @pytest.mark.asyncio
    async def test_all_healthy(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = _make_projections(
            "sys-1", "Backend", "org-1", ["acme/api", "acme/worker"]
        )
        handler = GetSystemStatusHandler(store, sys_proj, repo_proj)

        # Seed health data — both repos healthy
        await store.save("repo_health", "acme/api", {
            "total_executions": 10, "successful_executions": 10,
            "success_rate": 1.0, "last_execution_at": "2026-03-06T10:00:00",
        })
        await store.save("repo_health", "acme/worker", {
            "total_executions": 5, "successful_executions": 5,
            "success_rate": 1.0, "last_execution_at": "2026-03-06T09:00:00",
        })

        result = await handler.handle(GetSystemStatusQuery(system_id="sys-1"))

        assert result.system_id == "sys-1"
        assert result.system_name == "Backend"
        assert result.overall_status == "healthy"
        assert result.total_repos == 2
        assert result.healthy_repos == 2
        assert result.failing_repos == 0
        assert len(result.repos) == 2

    @pytest.mark.asyncio
    async def test_degraded_when_some_failing(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = _make_projections(
            "sys-1", "Backend", "org-1", ["acme/api", "acme/worker"]
        )
        handler = GetSystemStatusHandler(store, sys_proj, repo_proj)

        await store.save("repo_health", "acme/api", {
            "total_executions": 10, "successful_executions": 10, "success_rate": 1.0,
        })
        await store.save("repo_health", "acme/worker", {
            "total_executions": 10, "successful_executions": 2, "success_rate": 0.2,
        })

        result = await handler.handle(GetSystemStatusQuery(system_id="sys-1"))

        assert result.overall_status == "degraded"
        assert result.healthy_repos == 1
        assert result.failing_repos == 1

    @pytest.mark.asyncio
    async def test_empty_system(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = _make_projections(
            "sys-1", "Empty", "org-1", []
        )
        handler = GetSystemStatusHandler(store, sys_proj, repo_proj)

        result = await handler.handle(GetSystemStatusQuery(system_id="sys-1"))

        assert result.overall_status == "healthy"
        assert result.total_repos == 0
        assert len(result.repos) == 0
