"""Handler for GetContributionHeatmapQuery.

Lazy handler: resolves execution IDs from org/system/repo filters,
then queries TimescaleDB for daily activity buckets.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION
from syn_domain.contexts.organization.domain.read_models.contribution_heatmap import (
    ContributionHeatmapResult,
    HeatmapDayBucket,
)
from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
    TimescaleHeatmapQuery,
)

if TYPE_CHECKING:
    import asyncpg

    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
    from syn_domain.contexts.organization.domain.queries.get_contribution_heatmap import (
        GetContributionHeatmapQuery,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import (
        RepoProjection,
    )


_ZERO_BREAKDOWN: dict[str, float] = {
    "sessions": 0.0,
    "executions": 0.0,
    "commits": 0.0,
    "cost_usd": 0.0,
    "tokens": 0.0,
    "input_tokens": 0.0,
    "output_tokens": 0.0,
    "cache_creation_tokens": 0.0,
    "cache_read_tokens": 0.0,
}


def _empty_result(
    query: GetContributionHeatmapQuery,
    filter_meta: dict[str, str | None],
) -> ContributionHeatmapResult:
    """Build a zero-filled result for a date range with no matching executions."""
    days: list[HeatmapDayBucket] = []
    current = query.start_date
    while current <= query.end_date:
        days.append(
            HeatmapDayBucket(date=current.isoformat(), count=0.0, breakdown=dict(_ZERO_BREAKDOWN))
        )
        current += timedelta(days=1)
    return ContributionHeatmapResult(
        metric=query.metric,
        start_date=query.start_date.isoformat(),
        end_date=query.end_date.isoformat(),
        total=0.0,
        days=days,
        filter=filter_meta,
    )


class GetContributionHeatmapHandler:
    """Query handler: get daily activity buckets for a contribution heatmap."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        store: ProjectionStoreProtocol,
        repo_projection: RepoProjection,
    ) -> None:
        self._timescale = TimescaleHeatmapQuery(pool)
        self._store = store
        self._repo_projection = repo_projection

    async def _resolve_repo_names(self, query: GetContributionHeatmapQuery) -> set[str] | None:
        """Resolve repo full names from query filters, or None if no filter."""
        if query.repo_id:
            repo = await self._repo_projection.get(query.repo_id)
            return {repo.full_name} if repo else set()
        if query.system_id:
            repos = await self._repo_projection.list_all(system_id=query.system_id)
            return {r.full_name for r in repos}
        if query.organization_id:
            repos = await self._repo_projection.list_all(organization_id=query.organization_id)
            return {r.full_name for r in repos}
        return None

    async def _get_execution_ids(self, repo_names: set[str]) -> set[str]:
        """Get execution IDs correlated with the given repo names."""
        correlations = await self._store.get_all(REPO_CORRELATION)
        return {c["execution_id"] for c in correlations if c.get("repo_full_name") in repo_names}

    async def handle(self, query: GetContributionHeatmapQuery) -> ContributionHeatmapResult:
        """Handle GetContributionHeatmapQuery."""
        repo_names = await self._resolve_repo_names(query)
        execution_ids: set[str] | None = None
        if repo_names is not None:
            execution_ids = await self._get_execution_ids(repo_names)

        if execution_ids is not None and not execution_ids:
            return _empty_result(query, self._build_filter(query))

        buckets = await self._timescale.query(query.start_date, query.end_date, execution_ids)

        days = [
            HeatmapDayBucket(
                date=b.date,
                count=b.breakdown.get(query.metric, 0.0),
                breakdown=b.breakdown,
            )
            for b in buckets
        ]

        return ContributionHeatmapResult(
            metric=query.metric,
            start_date=query.start_date.isoformat(),
            end_date=query.end_date.isoformat(),
            total=sum(d.count for d in days),
            days=days,
            filter=self._build_filter(query),
        )

    @staticmethod
    def _build_filter(query: GetContributionHeatmapQuery) -> dict[str, str | None]:
        """Build filter metadata from query parameters."""
        return {
            "organization_id": query.organization_id,
            "system_id": query.system_id,
            "repo_id": query.repo_id,
        }
