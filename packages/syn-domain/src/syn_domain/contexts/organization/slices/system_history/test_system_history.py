"""Tests for GetSystemHistoryHandler."""

from __future__ import annotations

import pytest

from syn_domain.contexts.organization.domain.queries.get_system_history import (
    GetSystemHistoryQuery,
)
from syn_domain.contexts.organization.slices.conftest import (
    FakeProjectionStore,
    _make_projections,
)
from syn_domain.contexts.organization.slices.system_history.GetSystemHistoryHandler import (
    GetSystemHistoryHandler,
)


@pytest.mark.unit
class TestGetSystemHistoryHandler:
    @pytest.mark.asyncio
    async def test_returns_chronological_order(self) -> None:
        store = FakeProjectionStore()
        _, repo_proj = _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemHistoryHandler(store, repo_proj)

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

        await store.save(
            "workflow_executions",
            "exec-1",
            {
                "workflow_execution_id": "exec-1",
                "status": "completed",
                "started_at": "2026-03-06T10:00:00",
            },
        )
        await store.save(
            "workflow_executions",
            "exec-2",
            {
                "workflow_execution_id": "exec-2",
                "status": "completed",
                "started_at": "2026-03-05T08:00:00",
            },
        )

        result = await handler.handle(GetSystemHistoryQuery(system_id="sys-1"))

        assert len(result) == 2
        # Chronological: oldest first
        assert result[0].execution_id == "exec-2"
        assert result[1].execution_id == "exec-1"

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        store = FakeProjectionStore()
        _, repo_proj = _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemHistoryHandler(store, repo_proj)

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

        result = await handler.handle(GetSystemHistoryQuery(system_id="sys-1", limit=2))
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_for_unknown_system(self) -> None:
        store = FakeProjectionStore()
        _, repo_proj = _make_projections("sys-1", "Backend", "org-1", [])
        handler = GetSystemHistoryHandler(store, repo_proj)

        result = await handler.handle(GetSystemHistoryQuery(system_id="sys-1"))
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_offset_pagination(self) -> None:
        """Offset should skip entries before applying limit."""
        store = FakeProjectionStore()
        _, repo_proj = _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemHistoryHandler(store, repo_proj)

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

        result = await handler.handle(GetSystemHistoryQuery(system_id="sys-1", offset=2, limit=2))
        assert len(result) == 2
        # Chronological order: exec-0, exec-1, exec-2, exec-3, exec-4
        # offset=2 → skip exec-0 and exec-1
        assert result[0].execution_id == "exec-2"
        assert result[1].execution_id == "exec-3"

    @pytest.mark.asyncio
    async def test_offset_beyond_total(self) -> None:
        """Offset beyond total entries returns empty list."""
        store = FakeProjectionStore()
        _, repo_proj = _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemHistoryHandler(store, repo_proj)

        await store.save(
            "repo_correlation",
            "exec-0:acme/api",
            {
                "repo_full_name": "acme/api",
                "execution_id": "exec-0",
            },
        )
        await store.save(
            "workflow_executions",
            "exec-0",
            {
                "workflow_execution_id": "exec-0",
                "status": "completed",
                "started_at": "2026-03-06T10:00:00",
            },
        )

        result = await handler.handle(GetSystemHistoryQuery(system_id="sys-1", offset=100))
        assert len(result) == 0
