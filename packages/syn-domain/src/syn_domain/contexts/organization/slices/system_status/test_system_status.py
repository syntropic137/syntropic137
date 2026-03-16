"""Tests for GetSystemStatusHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain.queries.get_system_status import (
    GetSystemStatusQuery,
)
from syn_domain.contexts.organization.slices.conftest import (
    FakeProjectionStore,
    _make_projections,
)
from syn_domain.contexts.organization.slices.system_status.GetSystemStatusHandler import (
    GetSystemStatusHandler,
)


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
        await store.save(
            "repo_health",
            "acme/api",
            {
                "total_executions": 10,
                "successful_executions": 10,
                "success_rate": 1.0,
                "last_execution_at": "2026-03-06T10:00:00",
                "repo_full_name": "acme/api",
            },
        )
        await store.save(
            "repo_health",
            "acme/worker",
            {
                "total_executions": 5,
                "successful_executions": 5,
                "success_rate": 1.0,
                "last_execution_at": "2026-03-06T09:00:00",
                "repo_full_name": "acme/worker",
            },
        )

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

        await store.save(
            "repo_health",
            "acme/api",
            {
                "total_executions": 10,
                "successful_executions": 10,
                "success_rate": 1.0,
                "repo_full_name": "acme/api",
            },
        )
        await store.save(
            "repo_health",
            "acme/worker",
            {
                "total_executions": 10,
                "successful_executions": 2,
                "success_rate": 0.2,
                "repo_full_name": "acme/worker",
            },
        )

        result = await handler.handle(GetSystemStatusQuery(system_id="sys-1"))

        assert result.overall_status == "degraded"
        assert result.healthy_repos == 1
        assert result.failing_repos == 1

    @pytest.mark.asyncio
    async def test_empty_system(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = _make_projections("sys-1", "Empty", "org-1", [])
        handler = GetSystemStatusHandler(store, sys_proj, repo_proj)

        result = await handler.handle(GetSystemStatusQuery(system_id="sys-1"))

        assert result.overall_status == "healthy"
        assert result.total_repos == 0
        assert len(result.repos) == 0

    @pytest.mark.asyncio
    async def test_all_repos_failing(self) -> None:
        """When majority of repos are failing, overall status is 'failing'."""
        store = FakeProjectionStore()
        sys_proj, repo_proj = _make_projections(
            "sys-1", "Backend", "org-1", ["acme/api", "acme/worker", "acme/web"]
        )
        handler = GetSystemStatusHandler(store, sys_proj, repo_proj)

        for name in ["acme/api", "acme/worker", "acme/web"]:
            await store.save(
                "repo_health",
                name,
                {
                    "total_executions": 10,
                    "successful_executions": 1,
                    "success_rate": 0.1,
                    "repo_full_name": name,
                },
            )

        result = await handler.handle(GetSystemStatusQuery(system_id="sys-1"))

        assert result.overall_status == "failing"
        assert result.failing_repos == 3

    @pytest.mark.asyncio
    async def test_no_health_data_returns_inactive(self) -> None:
        """Repos with no health data should be marked inactive."""
        store = FakeProjectionStore()
        sys_proj, repo_proj = _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemStatusHandler(store, sys_proj, repo_proj)

        # No health data seeded
        result = await handler.handle(GetSystemStatusQuery(system_id="sys-1"))

        assert result.total_repos == 1
        assert result.repos[0].status == "inactive"
        assert result.overall_status == "healthy"
