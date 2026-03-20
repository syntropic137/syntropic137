"""Tests for GetSystemPatternsHandler."""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_domain.contexts.organization.domain.queries.get_system_patterns import (
    GetSystemPatternsQuery,
)
from syn_domain.contexts.organization.slices.conftest import (
    FakeProjectionStore,
    _make_projections,
)
from syn_domain.contexts.organization.slices.system_patterns.GetSystemPatternsHandler import (
    GetSystemPatternsHandler,
)


@pytest.mark.unit
class TestGetSystemPatternsHandler:
    @pytest.mark.asyncio
    async def test_groups_failures_by_error(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemPatternsHandler(store, sys_proj, repo_proj)

        # Correlate two executions
        await store.save(
            "repo_correlation",
            "exec-1:acme/api",
            {
                "repo_full_name": "acme/api",
                "execution_id": "exec-1",
            },
        )
        await store.save(
            "repo_correlation",
            "exec-2:acme/api",
            {
                "repo_full_name": "acme/api",
                "execution_id": "exec-2",
            },
        )

        # Two failed executions with same error
        await store.save(
            "workflow_executions",
            "exec-1",
            {
                "workflow_execution_id": "exec-1",
                "status": "failed",
                "error_type": "timeout",
                "error_message": "Timed out after 300s",
                "completed_at": "2026-03-06T10:00:00",
            },
        )
        await store.save(
            "workflow_executions",
            "exec-2",
            {
                "workflow_execution_id": "exec-2",
                "status": "failed",
                "error_type": "timeout",
                "error_message": "Timed out after 300s",
                "completed_at": "2026-03-06T11:00:00",
            },
        )

        result = await handler.handle(GetSystemPatternsQuery(system_id="sys-1"))

        assert len(result.failure_patterns) == 1
        assert result.failure_patterns[0].error_type == "timeout"
        assert result.failure_patterns[0].occurrence_count == 2
        assert "acme/api" in result.failure_patterns[0].affected_repos

    @pytest.mark.asyncio
    async def test_detects_cost_outliers(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _make_projections(
            "sys-1", "Backend", "org-1", ["acme/api", "acme/worker", "acme/web"]
        )
        handler = GetSystemPatternsHandler(store, sys_proj, repo_proj)

        # acme/api costs 100x more than others
        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "100.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )
        await store.save(
            "repo_cost",
            "acme/worker",
            {
                "total_cost_usd": "1.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )
        await store.save(
            "repo_cost",
            "acme/web",
            {
                "total_cost_usd": "1.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )

        result = await handler.handle(GetSystemPatternsQuery(system_id="sys-1"))

        assert len(result.cost_outliers) == 1
        assert result.cost_outliers[0].repo_full_name == "acme/api"
        assert result.cost_outliers[0].cost_usd == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _make_projections("sys-1", "Backend", "org-1", [])
        handler = GetSystemPatternsHandler(store, sys_proj, repo_proj)

        result = await handler.handle(GetSystemPatternsQuery(system_id="sys-1"))

        assert len(result.failure_patterns) == 0
        assert len(result.cost_outliers) == 0

    @pytest.mark.asyncio
    async def test_boundary_factor_3x(self) -> None:
        """Exactly 3x median should NOT be an outlier (>3x required)."""
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _make_projections(
            "sys-1", "Backend", "org-1", ["acme/api", "acme/worker"]
        )
        handler = GetSystemPatternsHandler(store, sys_proj, repo_proj)

        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "3.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )
        await store.save(
            "repo_cost",
            "acme/worker",
            {
                "total_cost_usd": "1.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )

        result = await handler.handle(GetSystemPatternsQuery(system_id="sys-1"))

        # median=2.00, factor=3.00/2.00=1.5 — not an outlier
        assert len(result.cost_outliers) == 0

    @pytest.mark.asyncio
    async def test_single_repo_no_outliers(self) -> None:
        """A single repo cannot be an outlier (need at least 2)."""
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemPatternsHandler(store, sys_proj, repo_proj)

        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "100.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )

        result = await handler.handle(GetSystemPatternsQuery(system_id="sys-1"))

        assert len(result.cost_outliers) == 0
