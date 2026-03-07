"""Tests for RepoCostProjection."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from syn_domain.contexts.organization.slices.repo_cost.projection import (
    RepoCostProjection,
)


class FakeProjectionStore:
    """Minimal in-memory store for unit tests."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    async def save(self, projection: str, key: str, data: dict[str, Any]) -> None:
        self._data.setdefault(projection, {})[key] = data

    async def get(self, projection: str, key: str) -> dict[str, Any] | None:
        return self._data.get(projection, {}).get(key)

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        return list(self._data.get(projection, {}).values())

    async def delete_all(self, projection: str) -> None:
        self._data.pop(projection, None)


async def _seed_correlation(store: FakeProjectionStore, repo: str, exec_id: str, wf_id: str = "wf-1") -> None:
    key = f"{exec_id}:{repo}"
    await store.save("repo_correlation", key, {
        "repo_full_name": repo,
        "execution_id": exec_id,
        "workflow_id": wf_id,
        "correlation_source": "trigger",
        "correlated_at": "2026-03-06T10:00:00",
    })


@pytest.mark.unit
class TestRepoCostProjection:
    @pytest.mark.asyncio
    async def test_completed_records_cost(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCostProjection(store)
        await _seed_correlation(store, "acme/api", "exec-1")

        await proj.on_workflow_completed({
            "execution_id": "exec-1",
            "workflow_id": "wf-1",
            "total_cost_usd": "5.00",
            "total_tokens": 10000,
            "total_input_tokens": 8000,
            "total_output_tokens": 2000,
        })

        cost = await proj.get_cost("acme/api")
        assert cost.total_cost_usd == Decimal("5.00")
        assert cost.total_tokens == 10000
        assert cost.total_input_tokens == 8000
        assert cost.total_output_tokens == 2000
        assert cost.execution_count == 1

    @pytest.mark.asyncio
    async def test_failed_also_records_cost(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCostProjection(store)
        await _seed_correlation(store, "acme/api", "exec-2")

        await proj.on_workflow_failed({
            "execution_id": "exec-2",
            "workflow_id": "wf-1",
            "total_cost_usd": "2.00",
            "total_tokens": 3000,
            "total_input_tokens": 2000,
            "total_output_tokens": 1000,
        })

        cost = await proj.get_cost("acme/api")
        assert cost.total_cost_usd == Decimal("2.00")
        assert cost.execution_count == 1

    @pytest.mark.asyncio
    async def test_cost_accumulates_across_executions(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCostProjection(store)
        await _seed_correlation(store, "acme/api", "exec-1")
        await _seed_correlation(store, "acme/api", "exec-2")

        await proj.on_workflow_completed({"execution_id": "exec-1", "workflow_id": "wf-1", "total_cost_usd": "3.00", "total_tokens": 1000, "total_input_tokens": 800, "total_output_tokens": 200})
        await proj.on_workflow_completed({"execution_id": "exec-2", "workflow_id": "wf-1", "total_cost_usd": "7.00", "total_tokens": 2000, "total_input_tokens": 1500, "total_output_tokens": 500})

        cost = await proj.get_cost("acme/api")
        assert cost.total_cost_usd == Decimal("10.00")
        assert cost.total_tokens == 3000
        assert cost.execution_count == 2

    @pytest.mark.asyncio
    async def test_cost_by_workflow_breakdown(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCostProjection(store)
        await _seed_correlation(store, "acme/api", "exec-1", "wf-deploy")
        await _seed_correlation(store, "acme/api", "exec-2", "wf-test")

        await proj.on_workflow_completed({"execution_id": "exec-1", "workflow_id": "wf-deploy", "total_cost_usd": "5.00", "total_tokens": 0, "total_input_tokens": 0, "total_output_tokens": 0})
        await proj.on_workflow_completed({"execution_id": "exec-2", "workflow_id": "wf-test", "total_cost_usd": "2.00", "total_tokens": 0, "total_input_tokens": 0, "total_output_tokens": 0})

        cost = await proj.get_cost("acme/api")
        assert cost.cost_by_workflow["wf-deploy"] == Decimal("5.00")
        assert cost.cost_by_workflow["wf-test"] == Decimal("2.00")

    @pytest.mark.asyncio
    async def test_uncorrelated_execution_ignored(self) -> None:
        store = FakeProjectionStore()
        proj = RepoCostProjection(store)

        await proj.on_workflow_completed({"execution_id": "exec-99", "workflow_id": "wf-1", "total_cost_usd": "10.00", "total_tokens": 0, "total_input_tokens": 0, "total_output_tokens": 0})

        all_costs = await proj.get_all_costs()
        assert len(all_costs) == 0
