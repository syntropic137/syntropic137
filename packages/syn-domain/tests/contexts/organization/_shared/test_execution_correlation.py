"""The correlation is ASKED FOR, not loaded and filtered (#1253)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.organization._shared.execution_correlation import executions_by_repo
from syn_domain.contexts.organization.domain.queries.get_contribution_heatmap import (
    GetContributionHeatmapQuery,
)
from syn_domain.contexts.organization.slices.conftest import (
    Ask,
    AskFilter,
    FakeProjectionStore,
    _make_projections,
)
from syn_domain.contexts.organization.slices.contribution_heatmap.GetContributionHeatmapHandler import (
    GetContributionHeatmapHandler,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_CORRELATION = "repo_correlation"


def _by_repo(*repos: str) -> Ask:
    """The one read `executions_by_repo` is allowed to perform."""
    return Ask(_CORRELATION, (AskFilter("repo_full_name", repos),))


async def _store_with(correlations: Sequence[tuple[str, str]]) -> FakeProjectionStore:
    store = FakeProjectionStore()
    for execution_id, repo in correlations:
        await store.save(
            _CORRELATION,
            f"{execution_id}:{repo}",
            {"execution_id": execution_id, "repo_full_name": repo},
        )
    store.asks.clear()
    store.scans.clear()
    return store


@pytest.mark.unit
class TestExecutionsByRepo:
    @pytest.mark.asyncio
    async def test_asks_the_store_for_the_repos_it_wants(self) -> None:
        store = await _store_with([("exec-1", "acme/api"), ("exec-2", "acme/web")])

        found = await executions_by_repo(store, ["acme/api"])

        assert found == {"exec-1": "acme/api"}
        assert store.asks == [_by_repo("acme/api")]

    @pytest.mark.asyncio
    async def test_several_repos_are_one_ask(self) -> None:
        """A system with twelve repos must not cost twelve round trips."""
        store = await _store_with(
            [("exec-1", "acme/api"), ("exec-2", "acme/web"), ("exec-3", "other/thing")]
        )

        found = await executions_by_repo(store, ["acme/api", "acme/web"])

        assert found == {"exec-1": "acme/api", "exec-2": "acme/web"}
        assert store.asks == [_by_repo("acme/api", "acme/web")]

    @pytest.mark.asyncio
    async def test_the_whole_projection_is_never_loaded_to_answer_a_filter(self) -> None:
        """Loading every correlation and filtering in Python was the second of the
        two full scans behind the 8-15s heatmap. Both spellings return the same
        executions, so only the ask distinguishes them."""
        store = await _store_with([("exec-1", "acme/api"), ("exec-2", "acme/web")])

        await executions_by_repo(store, ["acme/api"])

        assert store.scans == []

    @pytest.mark.asyncio
    async def test_no_repos_matches_nothing_without_asking(self) -> None:
        """A filter that resolved to no repos must not widen to everything."""
        store = await _store_with([("exec-1", "acme/api")])

        assert await executions_by_repo(store, []) == {}
        assert store.asks == []
        assert store.scans == []

    @pytest.mark.asyncio
    async def test_half_written_record_is_skipped(self) -> None:
        store = FakeProjectionStore()
        await store.save(_CORRELATION, "orphan", {"repo_full_name": "acme/api"})

        assert await executions_by_repo(store, ["acme/api"]) == {}


@pytest.mark.unit
class TestHeatmapHandlerReadsFiltered:
    @pytest.mark.asyncio
    async def test_system_filter_never_loads_the_whole_correlation(self) -> None:
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = MagicMock()
        pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None)
            )
        )
        store = await _store_with([("exec-1", "acme/api"), ("exec-2", "other/thing")])
        _, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"], store)

        handler = GetContributionHeatmapHandler(pool=pool, store=store, repo_projection=repo_proj)
        result = await handler.handle(
            GetContributionHeatmapQuery(
                system_id="sys-1",
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 1),
                metric="sessions",
            )
        )

        assert result.filter["system_id"] == "sys-1"
        assert _by_repo("acme/api") in store.asks
        assert _CORRELATION not in store.scans
