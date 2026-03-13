"""Tests for RepoHealthProjection."""

from __future__ import annotations

from typing import Any

import pytest

from syn_domain.contexts.organization.slices.repo_health.projection import (
    RepoHealthProjection,
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

    async def query(
        self, projection: str, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        records = list(self._data.get(projection, {}).values())
        if filters:
            records = [r for r in records if all(r.get(k) == v for k, v in filters.items())]
        return records

    async def delete_all(self, projection: str) -> None:
        self._data.pop(projection, None)


async def _seed_correlation(store: FakeProjectionStore, repo: str, exec_id: str) -> None:
    """Seed a repo-execution correlation in the store."""
    key = f"{exec_id}:{repo}"
    await store.save(
        "repo_correlation",
        key,
        {
            "repo_full_name": repo,
            "execution_id": exec_id,
            "workflow_id": "wf-1",
            "correlation_source": "trigger",
            "correlated_at": "2026-03-06T10:00:00",
        },
    )


@pytest.mark.unit
class TestRepoHealthProjection:
    @pytest.mark.asyncio
    async def test_workflow_completed_updates_health(self) -> None:
        store = FakeProjectionStore()
        proj = RepoHealthProjection(store)
        await _seed_correlation(store, "acme/api", "exec-1")

        await proj.on_workflow_completed(
            {
                "execution_id": "exec-1",
                "total_cost_usd": "1.50",
                "total_tokens": 5000,
                "completed_at": "2026-03-06T10:05:00",
            }
        )

        health = await proj.get_health("acme/api")
        assert health.total_executions == 1
        assert health.successful_executions == 1
        assert health.failed_executions == 0
        assert health.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_workflow_failed_updates_health(self) -> None:
        store = FakeProjectionStore()
        proj = RepoHealthProjection(store)
        await _seed_correlation(store, "acme/api", "exec-2")

        await proj.on_workflow_failed(
            {
                "execution_id": "exec-2",
                "total_cost_usd": "0.50",
                "total_tokens": 1000,
                "failed_at": "2026-03-06T10:05:00",
            }
        )

        health = await proj.get_health("acme/api")
        assert health.total_executions == 1
        assert health.successful_executions == 0
        assert health.failed_executions == 1
        assert health.success_rate == 0.0

    @pytest.mark.asyncio
    async def test_multiple_executions_compute_rate(self) -> None:
        store = FakeProjectionStore()
        proj = RepoHealthProjection(store)
        await _seed_correlation(store, "acme/api", "exec-1")
        await _seed_correlation(store, "acme/api", "exec-2")
        await _seed_correlation(store, "acme/api", "exec-3")

        await proj.on_workflow_completed(
            {
                "execution_id": "exec-1",
                "total_cost_usd": "1",
                "total_tokens": 100,
                "completed_at": "",
            }
        )
        await proj.on_workflow_completed(
            {
                "execution_id": "exec-2",
                "total_cost_usd": "1",
                "total_tokens": 100,
                "completed_at": "",
            }
        )
        await proj.on_workflow_failed(
            {"execution_id": "exec-3", "total_cost_usd": "1", "total_tokens": 100, "failed_at": ""}
        )

        health = await proj.get_health("acme/api")
        assert health.total_executions == 3
        assert health.successful_executions == 2
        assert health.failed_executions == 1
        assert abs(health.success_rate - 2 / 3) < 0.01

    @pytest.mark.asyncio
    async def test_uncorrelated_execution_is_ignored(self) -> None:
        store = FakeProjectionStore()
        proj = RepoHealthProjection(store)
        # No correlation seeded

        await proj.on_workflow_completed(
            {
                "execution_id": "exec-99",
                "total_cost_usd": "1",
                "total_tokens": 100,
                "completed_at": "",
            }
        )

        all_health = await proj.get_all_health()
        assert len(all_health) == 0

    @pytest.mark.asyncio
    async def test_cost_and_tokens_accumulate(self) -> None:
        store = FakeProjectionStore()
        proj = RepoHealthProjection(store)
        await _seed_correlation(store, "acme/api", "exec-1")
        await _seed_correlation(store, "acme/api", "exec-2")

        await proj.on_workflow_completed(
            {
                "execution_id": "exec-1",
                "total_cost_usd": "2.50",
                "total_tokens": 1000,
                "completed_at": "",
            }
        )
        await proj.on_workflow_completed(
            {
                "execution_id": "exec-2",
                "total_cost_usd": "3.50",
                "total_tokens": 2000,
                "completed_at": "",
            }
        )

        health = await proj.get_health("acme/api")
        assert str(health.window_cost_usd) == "6.00"
        assert health.window_tokens == 3000

    @pytest.mark.asyncio
    async def test_multi_repo_execution(self) -> None:
        store = FakeProjectionStore()
        proj = RepoHealthProjection(store)
        await _seed_correlation(store, "acme/api", "exec-1")
        await _seed_correlation(store, "acme/web", "exec-1")

        await proj.on_workflow_completed(
            {
                "execution_id": "exec-1",
                "total_cost_usd": "1",
                "total_tokens": 100,
                "completed_at": "",
            }
        )

        api_health = await proj.get_health("acme/api")
        web_health = await proj.get_health("acme/web")
        assert api_health.total_executions == 1
        assert web_health.total_executions == 1
