"""Tests for GetGlobalOverviewHandler."""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_domain.contexts.organization.domain.queries.get_global_overview import (
    GetGlobalOverviewQuery,
)
from syn_domain.contexts.organization.slices.conftest import FakeProjectionStore
from syn_domain.contexts.organization.slices.global_overview.GetGlobalOverviewHandler import (
    GetGlobalOverviewHandler,
)
from syn_domain.contexts.organization.slices.list_repos.projection import RepoProjection
from syn_domain.contexts.organization.slices.list_systems.projection import SystemProjection


async def _setup_projections() -> tuple[SystemProjection, RepoProjection]:
    """Create projections with two systems and some repos."""
    from syn_domain.contexts.organization.domain.events.RepoAssignedToSystemEvent import (
        RepoAssignedToSystemEvent,
    )
    from syn_domain.contexts.organization.domain.events.RepoRegisteredEvent import (
        RepoRegisteredEvent,
    )
    from syn_domain.contexts.organization.domain.events.SystemCreatedEvent import (
        SystemCreatedEvent,
    )

    store = FakeProjectionStore()
    sys_proj = SystemProjection(store=store)
    repo_proj = RepoProjection(store=store)

    await sys_proj.handle_system_created(
        SystemCreatedEvent(
            system_id="sys-1",
            organization_id="org-1",
            name="Backend",
            description="",
            created_by="test",
        )
    )
    await sys_proj.handle_system_created(
        SystemCreatedEvent(
            system_id="sys-2",
            organization_id="org-1",
            name="Frontend",
            description="",
            created_by="test",
        )
    )

    # Register repos
    await repo_proj.handle_repo_registered(
        RepoRegisteredEvent(
            repo_id="r-1",
            organization_id="org-1",
            provider="github",
            provider_repo_id="",
            full_name="acme/api",
            owner="acme",
            default_branch="main",
            installation_id="",
            is_private=False,
            created_by="test",
        )
    )
    await repo_proj.handle_repo_assigned_to_system(
        RepoAssignedToSystemEvent(repo_id="r-1", system_id="sys-1")
    )

    # Unassigned repo
    await repo_proj.handle_repo_registered(
        RepoRegisteredEvent(
            repo_id="r-2",
            organization_id="org-1",
            provider="github",
            provider_repo_id="",
            full_name="acme/orphan",
            owner="acme",
            default_branch="main",
            installation_id="",
            is_private=False,
            created_by="test",
        )
    )

    return sys_proj, repo_proj


@pytest.mark.unit
class TestGetGlobalOverviewHandler:
    @pytest.mark.asyncio
    async def test_aggregates_systems_and_repos(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _setup_projections()
        handler = GetGlobalOverviewHandler(store, sys_proj, repo_proj)

        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "10.00",
                "total_tokens": 500,
                "repo_full_name": "acme/api",
            },
        )

        result = await handler.handle(GetGlobalOverviewQuery())

        assert result.total_systems == 2
        assert result.total_repos == 2
        assert result.unassigned_repos == 1
        assert result.total_cost_usd == Decimal("10.00")
        assert len(result.systems) == 2

    @pytest.mark.asyncio
    async def test_empty_when_no_systems(self) -> None:
        store = FakeProjectionStore()
        handler = GetGlobalOverviewHandler(
            store, SystemProjection(store=store), RepoProjection(store=store)
        )

        result = await handler.handle(GetGlobalOverviewQuery())

        assert result.total_systems == 0
        assert result.total_repos == 0
        assert result.total_cost_usd == Decimal("0")

    @pytest.mark.asyncio
    async def test_partial_data(self) -> None:
        """Repos with cost but no health, and vice versa."""
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _setup_projections()
        handler = GetGlobalOverviewHandler(store, sys_proj, repo_proj)

        # acme/api has cost but no health
        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "5.00",
                "total_tokens": 100,
                "repo_full_name": "acme/api",
            },
        )
        # acme/orphan has health but no cost (unassigned, so doesn't affect systems)
        await store.save(
            "repo_health",
            "acme/orphan",
            {
                "total_executions": 3,
                "success_rate": 0.9,
                "repo_full_name": "acme/orphan",
            },
        )

        result = await handler.handle(GetGlobalOverviewQuery())

        assert result.total_cost_usd == Decimal("5.00")
        # Backend system (sys-1) has acme/api with cost but no health → healthy status
        backend = next(s for s in result.systems if s.system_name == "Backend")
        assert backend.overall_status == "healthy"
        assert backend.total_cost_usd == Decimal("5.00")
