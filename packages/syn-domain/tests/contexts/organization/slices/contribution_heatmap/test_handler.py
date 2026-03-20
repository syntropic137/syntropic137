"""Tests for GetContributionHeatmapHandler."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.organization.domain.queries.get_contribution_heatmap import (
    GetContributionHeatmapQuery,
)
from syn_domain.contexts.organization.slices.conftest import (
    FakeProjectionStore,
    _make_projections,
)
from syn_domain.contexts.organization.slices.contribution_heatmap.GetContributionHeatmapHandler import (
    GetContributionHeatmapHandler,
)


class _FakeRow:
    """Fake asyncpg Record that supports both attribute and bracket access."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


def _make_mock_pool(rows: list[dict[str, Any]]) -> MagicMock:
    """Create a mock asyncpg pool that returns the given rows."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_FakeRow(r) for r in rows])

    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None)
        )
    )
    return pool


def _make_row(
    day: date,
    sessions: int = 0,
    executions: int = 0,
    commits: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> dict[str, Any]:
    """Create a mock DB row matching the TimescaleDB query columns."""
    return {
        "day": day,
        "sessions": sessions,
        "executions": executions,
        "commits": commits,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
    }


@pytest.mark.unit
class TestGetContributionHeatmapHandler:
    @pytest.mark.asyncio
    async def test_no_filter_returns_all(self) -> None:
        """With no filter, queries all events (execution_ids=None)."""
        pool = _make_mock_pool(
            [
                _make_row(date(2026, 3, 1), sessions=3, executions=1),
                _make_row(date(2026, 3, 2), sessions=1),
            ]
        )
        store = FakeProjectionStore()
        _, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])

        handler = GetContributionHeatmapHandler(pool=pool, store=store, repo_projection=repo_proj)
        result = await handler.handle(
            GetContributionHeatmapQuery(
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 2),
                metric="sessions",
            )
        )

        assert result.metric == "sessions"
        assert result.total == 4.0
        assert len(result.days) == 2
        assert result.days[0].count == 3.0
        assert result.days[1].count == 1.0

    @pytest.mark.asyncio
    async def test_system_filter_resolves_execution_ids(self) -> None:
        """System filter resolves repos → correlation → execution_ids."""
        pool = _make_mock_pool(
            [
                _make_row(date(2026, 3, 1), executions=2),
            ]
        )
        store = FakeProjectionStore()
        _, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])

        await store.save(
            "repo_correlation",
            "exec-1:acme/api",
            {
                "repo_full_name": "acme/api",
                "execution_id": "exec-1",
            },
        )

        handler = GetContributionHeatmapHandler(pool=pool, store=store, repo_projection=repo_proj)
        result = await handler.handle(
            GetContributionHeatmapQuery(
                system_id="sys-1",
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 1),
                metric="executions",
            )
        )

        assert result.metric == "executions"
        assert result.filter["system_id"] == "sys-1"

    @pytest.mark.asyncio
    async def test_empty_range_returns_empty(self) -> None:
        """Filter that resolves to no execution IDs returns empty result."""
        pool = _make_mock_pool([])
        store = FakeProjectionStore()
        _, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        # No correlations in store → empty execution_ids

        handler = GetContributionHeatmapHandler(pool=pool, store=store, repo_projection=repo_proj)
        result = await handler.handle(
            GetContributionHeatmapQuery(
                system_id="sys-1",
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 5),
            )
        )

        assert result.total == 0.0
        assert len(result.days) == 5  # zero-filled for Mar 1-5
        assert all(d.count == 0.0 for d in result.days)

    @pytest.mark.asyncio
    async def test_metric_selection_sets_count(self) -> None:
        """The selected metric determines the count field on each bucket."""
        pool = _make_mock_pool(
            [
                _make_row(date(2026, 3, 1), sessions=5, input_tokens=1000, output_tokens=500),
            ]
        )
        store = FakeProjectionStore()
        _, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])

        handler = GetContributionHeatmapHandler(pool=pool, store=store, repo_projection=repo_proj)

        result_sessions = await handler.handle(
            GetContributionHeatmapQuery(
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 1),
                metric="sessions",
            )
        )
        assert result_sessions.days[0].count == 5.0

        result_tokens = await handler.handle(
            GetContributionHeatmapQuery(
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 1),
                metric="tokens",
            )
        )
        assert result_tokens.days[0].count == 1500.0
