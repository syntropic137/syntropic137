"""Tests for GetSystemCostHandler."""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_domain.contexts.organization.domain.queries.get_system_cost import (
    GetSystemCostQuery,
)
from syn_domain.contexts.organization.slices.conftest import (
    FakeProjectionStore,
    _make_projections,
)
from syn_domain.contexts.organization.slices.system_cost.GetSystemCostHandler import (
    GetSystemCostHandler,
)


@pytest.mark.unit
class TestGetSystemCostHandler:
    @pytest.mark.asyncio
    async def test_aggregates_repo_costs(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = _make_projections(
            "sys-1", "Backend", "org-1", ["acme/api", "acme/worker"]
        )
        handler = GetSystemCostHandler(store, sys_proj, repo_proj)

        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "5.50",
                "total_tokens": 1000,
                "total_input_tokens": 600,
                "total_output_tokens": 400,
                "execution_count": 3,
                "cost_by_workflow": {"wf-deploy": "3.00", "wf-test": "2.50"},
                "cost_by_model": {"claude-3": "5.50"},
            },
        )
        await store.save(
            "repo_cost",
            "acme/worker",
            {
                "total_cost_usd": "2.00",
                "total_tokens": 500,
                "total_input_tokens": 300,
                "total_output_tokens": 200,
                "execution_count": 1,
                "cost_by_workflow": {"wf-deploy": "2.00"},
                "cost_by_model": {"claude-3": "2.00"},
            },
        )

        result = await handler.handle(GetSystemCostQuery(system_id="sys-1"))

        assert result.system_id == "sys-1"
        assert result.total_cost_usd == Decimal("7.50")
        assert result.total_tokens == 1500
        assert result.execution_count == 4
        assert result.cost_by_repo["acme/api"] == Decimal("5.50")
        assert result.cost_by_workflow["wf-deploy"] == Decimal("5.00")
        assert result.cost_by_model["claude-3"] == Decimal("7.50")

    @pytest.mark.asyncio
    async def test_empty_when_no_costs(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemCostHandler(store, sys_proj, repo_proj)

        result = await handler.handle(GetSystemCostQuery(system_id="sys-1"))

        assert result.total_cost_usd == Decimal("0")
        assert result.execution_count == 0

    @pytest.mark.asyncio
    async def test_partial_cost_data(self) -> None:
        """Some repos have cost data, some don't — totals only include available data."""
        store = FakeProjectionStore()
        sys_proj, repo_proj = _make_projections(
            "sys-1", "Backend", "org-1", ["acme/api", "acme/worker"]
        )
        handler = GetSystemCostHandler(store, sys_proj, repo_proj)

        # Only acme/api has cost data
        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "5.00",
                "total_tokens": 1000,
                "total_input_tokens": 600,
                "total_output_tokens": 400,
                "execution_count": 2,
                "cost_by_workflow": {},
                "cost_by_model": {},
            },
        )

        result = await handler.handle(GetSystemCostQuery(system_id="sys-1"))

        assert result.total_cost_usd == Decimal("5.00")
        assert result.execution_count == 2
        assert "acme/worker" not in result.cost_by_repo
