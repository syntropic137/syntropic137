"""Tests for GetGlobalCostHandler."""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_domain.contexts.organization.domain.queries.get_global_cost import (
    GetGlobalCostQuery,
)
from syn_domain.contexts.organization.slices.conftest import FakeProjectionStore
from syn_domain.contexts.organization.slices.global_cost.GetGlobalCostHandler import (
    GetGlobalCostHandler,
)
from syn_domain.contexts.organization.slices.global_overview.test_global_overview import (
    _setup_projections,
)


@pytest.mark.unit
class TestGetGlobalCostHandler:
    @pytest.mark.asyncio
    async def test_aggregates_all_repo_costs(self) -> None:
        store = FakeProjectionStore()
        _, repo_proj = _setup_projections()
        handler = GetGlobalCostHandler(store, repo_proj)

        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "5.00",
                "total_tokens": 1000,
                "total_input_tokens": 600,
                "total_output_tokens": 400,
                "execution_count": 2,
                "cost_by_workflow": {"wf-deploy": "5.00"},
                "cost_by_model": {"claude-3": "5.00"},
            },
        )
        await store.save(
            "repo_cost",
            "acme/orphan",
            {
                "total_cost_usd": "3.00",
                "total_tokens": 500,
                "total_input_tokens": 300,
                "total_output_tokens": 200,
                "execution_count": 1,
                "cost_by_workflow": {"wf-test": "3.00"},
                "cost_by_model": {"claude-3": "3.00"},
            },
        )

        result = await handler.handle(GetGlobalCostQuery())

        assert result.total_cost_usd == Decimal("8.00")
        assert result.total_tokens == 1500
        assert result.execution_count == 3
        assert result.cost_by_repo["acme/api"] == Decimal("5.00")
        assert result.cost_by_repo["acme/orphan"] == Decimal("3.00")
        assert result.cost_by_model["claude-3"] == Decimal("8.00")

    @pytest.mark.asyncio
    async def test_empty_when_no_costs(self) -> None:
        from syn_domain.contexts.organization.slices.list_repos.projection import (
            RepoProjection,
        )

        store = FakeProjectionStore()
        handler = GetGlobalCostHandler(store, RepoProjection())

        result = await handler.handle(GetGlobalCostQuery())

        assert result.total_cost_usd == Decimal("0")
        assert result.execution_count == 0
