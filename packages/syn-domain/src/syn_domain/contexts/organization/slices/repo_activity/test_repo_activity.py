"""Tests for GetRepoActivityHandler."""

from __future__ import annotations

from typing import Any

import pytest

from syn_domain.contexts.organization.domain.queries.get_repo_activity import (
    GetRepoActivityQuery,
)
from syn_domain.contexts.organization.slices.repo_activity.handler import (
    GetRepoActivityHandler,
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


@pytest.mark.unit
class TestGetRepoActivityHandler:
    @pytest.mark.asyncio
    async def test_returns_correlated_executions(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoActivityHandler(store)

        # Seed correlation
        await store.save("repo_correlation", "exec-1:acme/api", {
            "repo_full_name": "acme/api", "execution_id": "exec-1",
        })
        # Seed execution
        await store.save("workflow_executions", "exec-1", {
            "workflow_execution_id": "exec-1",
            "workflow_id": "wf-1",
            "workflow_name": "Deploy",
            "status": "completed",
            "started_at": "2026-03-06T10:00:00",
            "completed_at": "2026-03-06T10:05:00",
        })

        result = await handler.handle(GetRepoActivityQuery(repo_id="acme/api"))
        assert len(result) == 1
        assert result[0].execution_id == "exec-1"
        assert result[0].workflow_name == "Deploy"

    @pytest.mark.asyncio
    async def test_filters_out_uncorrelated_executions(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoActivityHandler(store)

        await store.save("repo_correlation", "exec-1:acme/api", {
            "repo_full_name": "acme/api", "execution_id": "exec-1",
        })
        await store.save("workflow_executions", "exec-1", {
            "workflow_execution_id": "exec-1", "status": "completed", "started_at": "",
        })
        await store.save("workflow_executions", "exec-2", {
            "workflow_execution_id": "exec-2", "status": "completed", "started_at": "",
        })

        result = await handler.handle(GetRepoActivityQuery(repo_id="acme/api"))
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_pagination(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoActivityHandler(store)

        for i in range(5):
            await store.save("repo_correlation", f"exec-{i}:acme/api", {
                "repo_full_name": "acme/api", "execution_id": f"exec-{i}",
            })
            await store.save("workflow_executions", f"exec-{i}", {
                "workflow_execution_id": f"exec-{i}", "status": "completed",
                "started_at": f"2026-03-06T10:0{i}:00",
            })

        result = await handler.handle(GetRepoActivityQuery(repo_id="acme/api", limit=2, offset=1))
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_for_unknown_repo(self) -> None:
        store = FakeProjectionStore()
        handler = GetRepoActivityHandler(store)

        result = await handler.handle(GetRepoActivityQuery(repo_id="unknown/repo"))
        assert len(result) == 0
