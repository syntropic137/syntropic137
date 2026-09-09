"""The correlation is ASKED FOR, not loaded and filtered (#1253)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.organization._shared.execution_correlation import executions_by_repo
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

if TYPE_CHECKING:
    from collections.abc import Sequence


class _NoFullScanStore(FakeProjectionStore):
    """A store that refuses to hand over the whole correlation projection.

    Loading every correlation record and filtering it in Python was the second
    of the two full scans behind the 8-15s contribution heatmap. A test that
    only checked the RESULT would pass either way, because both spellings
    return the same executions - so this asserts on the ask.

    Only ``repo_correlation`` is refused. The repo list is a different
    projection, small and bounded by how many repos an org has; loading it is
    not the defect under test here.
    """

    def __init__(self) -> None:
        super().__init__()
        self.filters_seen: list[dict[str, Any]] = []

    async def get_all(self, projection: str) -> list[dict[str, Any]]:
        if projection == "repo_correlation":
            msg = "get_all('repo_correlation'): the whole table was loaded to answer a filter"
            raise AssertionError(msg)
        return await super().get_all(projection)

    async def query(
        self,
        projection: str,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.filters_seen.append(dict(filters or {}))
        return await super().query(projection, filters, order_by, limit, offset)


async def _store_with(correlations: Sequence[tuple[str, str]]) -> _NoFullScanStore:
    store = _NoFullScanStore()
    for execution_id, repo in correlations:
        await store.save(
            "repo_correlation",
            f"{execution_id}:{repo}",
            {"execution_id": execution_id, "repo_full_name": repo},
        )
    return store


@pytest.mark.unit
class TestExecutionsByRepo:
    @pytest.mark.asyncio
    async def test_asks_the_store_for_the_repos_it_wants(self) -> None:
        store = await _store_with([("exec-1", "acme/api"), ("exec-2", "acme/web")])

        found = await executions_by_repo(store, ["acme/api"])

        assert found == {"exec-1": "acme/api"}
        assert store.filters_seen == [{"repo_full_name": ["acme/api"]}]

    @pytest.mark.asyncio
    async def test_several_repos_are_one_ask(self) -> None:
        """A system with twelve repos must not cost twelve round trips."""
        store = await _store_with(
            [("exec-1", "acme/api"), ("exec-2", "acme/web"), ("exec-3", "other/thing")]
        )

        found = await executions_by_repo(store, ["acme/api", "acme/web"])

        assert found == {"exec-1": "acme/api", "exec-2": "acme/web"}
        assert len(store.filters_seen) == 1

    @pytest.mark.asyncio
    async def test_no_repos_matches_nothing_without_asking(self) -> None:
        """A filter that resolved to no repos must not widen to everything."""
        store = await _store_with([("exec-1", "acme/api")])

        assert await executions_by_repo(store, []) == {}
        assert store.filters_seen == []

    @pytest.mark.asyncio
    async def test_half_written_record_is_skipped(self) -> None:
        store = _NoFullScanStore()
        await store.save("repo_correlation", "orphan", {"repo_full_name": "acme/api"})

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
        assert {"repo_full_name": ["acme/api"]} in store.filters_seen
