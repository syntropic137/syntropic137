"""Tests for GetSystemActivityHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain.queries.get_system_activity import (
    GetSystemActivityQuery,
)
from syn_domain.contexts.organization.slices.conftest import (
    FakeProjectionStore,
    _make_projections,
)
from syn_domain.contexts.organization.slices.system_activity.GetSystemActivityHandler import (
    GetSystemActivityHandler,
)


@pytest.mark.unit
class TestGetSystemActivityHandler:
    @pytest.mark.asyncio
    async def test_returns_correlated_executions(self) -> None:
        store = FakeProjectionStore()
        _, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemActivityHandler(store, repo_proj)

        await store.save(
            "repo_correlation",
            "exec-1:acme/api",
            {
                "repo_full_name": "acme/api",
                "execution_id": "exec-1",
            },
        )
        await store.save(
            "workflow_executions",
            "exec-1",
            {
                "workflow_execution_id": "exec-1",
                "workflow_name": "Deploy",
                "status": "completed",
                "started_at": "2026-03-06T10:00:00",
            },
        )

        result = await handler.handle(GetSystemActivityQuery(system_id="sys-1"))
        assert len(result) == 1
        assert result[0].execution_id == "exec-1"
        assert result[0].workflow_name == "Deploy"

    @pytest.mark.asyncio
    async def test_filters_out_unrelated_repos(self) -> None:
        store = FakeProjectionStore()
        _, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemActivityHandler(store, repo_proj)

        # Correlation for a repo NOT in the system
        await store.save(
            "repo_correlation",
            "exec-1:other/repo",
            {
                "repo_full_name": "other/repo",
                "execution_id": "exec-1",
            },
        )
        await store.save(
            "workflow_executions",
            "exec-1",
            {
                "workflow_execution_id": "exec-1",
                "status": "completed",
                "started_at": "",
            },
        )

        result = await handler.handle(GetSystemActivityQuery(system_id="sys-1"))
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_pagination(self) -> None:
        store = FakeProjectionStore()
        _, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemActivityHandler(store, repo_proj)

        for i in range(5):
            await store.save(
                "repo_correlation",
                f"exec-{i}:acme/api",
                {
                    "repo_full_name": "acme/api",
                    "execution_id": f"exec-{i}",
                },
            )
            await store.save(
                "workflow_executions",
                f"exec-{i}",
                {
                    "workflow_execution_id": f"exec-{i}",
                    "status": "completed",
                    "started_at": f"2026-03-06T10:0{i}:00",
                },
            )

        result = await handler.handle(GetSystemActivityQuery(system_id="sys-1", limit=2, offset=1))
        assert len(result) == 2
