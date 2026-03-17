"""Handler for GetContributionHeatmapQuery.

Lazy handler: resolves execution IDs from org/system/repo filters,
then queries TimescaleDB for daily activity buckets.
"""

from __future__ import annotations

from typing import Any

from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION
from syn_domain.contexts.organization.domain.queries.get_contribution_heatmap import (
    GetContributionHeatmapQuery,
)
from syn_domain.contexts.organization.domain.read_models.contribution_heatmap import (
    ContributionHeatmapResult,
    HeatmapDayBucket,
)
from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
    TimescaleHeatmapQuery,
)
from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)


class GetContributionHeatmapHandler:
    """Query handler: get daily activity buckets for a contribution heatmap."""

    def __init__(
        self,
        pool: Any,
        store: ProjectionStoreProtocol,
        repo_projection: RepoProjection,
    ) -> None:
        self._timescale = TimescaleHeatmapQuery(pool)
        self._store = store
        self._repo_projection = repo_projection

    async def _get_execution_ids_for_repo(self, repo_id: str) -> set[str]:
        """Resolve execution IDs for a single repo."""
        repo = self._repo_projection.get(repo_id)
        if not repo:
            return set()

        correlations = await self._store.get_all(REPO_CORRELATION)
        return {
            c["execution_id"]
            for c in correlations
            if c.get("repo_full_name") == repo.full_name
        }

    async def _get_execution_ids_for_system(self, system_id: str) -> set[str]:
        """Resolve execution IDs for all repos in a system."""
        repos = self._repo_projection.list_all(system_id=system_id)
        repo_names = {r.full_name for r in repos}

        correlations = await self._store.get_all(REPO_CORRELATION)
        return {
            c["execution_id"]
            for c in correlations
            if c.get("repo_full_name") in repo_names
        }

    async def _get_execution_ids_for_organization(self, organization_id: str) -> set[str]:
        """Resolve execution IDs for all repos in an organization."""
        repos = self._repo_projection.list_all(organization_id=organization_id)
        repo_names = {r.full_name for r in repos}

        correlations = await self._store.get_all(REPO_CORRELATION)
        return {
            c["execution_id"]
            for c in correlations
            if c.get("repo_full_name") in repo_names
        }

    async def handle(self, query: GetContributionHeatmapQuery) -> ContributionHeatmapResult:
        """Handle GetContributionHeatmapQuery."""
        # Resolve execution_ids from the most specific filter
        execution_ids: set[str] | None = None
        if query.repo_id:
            execution_ids = await self._get_execution_ids_for_repo(query.repo_id)
        elif query.system_id:
            execution_ids = await self._get_execution_ids_for_system(query.system_id)
        elif query.organization_id:
            execution_ids = await self._get_execution_ids_for_organization(query.organization_id)

        # If a filter was applied but resolved to zero executions, return empty
        if execution_ids is not None and not execution_ids:
            return ContributionHeatmapResult(
                metric=query.metric,
                start_date=query.start_date.isoformat(),
                end_date=query.end_date.isoformat(),
                total=0.0,
                days=[],
                filter=self._build_filter(query),
            )

        buckets = await self._timescale.query(query.start_date, query.end_date, execution_ids)

        # Set count from selected metric
        days = [
            HeatmapDayBucket(
                date=b.date,
                count=b.breakdown.get(query.metric, 0.0),
                breakdown=b.breakdown,
            )
            for b in buckets
        ]

        total = sum(d.count for d in days)

        return ContributionHeatmapResult(
            metric=query.metric,
            start_date=query.start_date.isoformat(),
            end_date=query.end_date.isoformat(),
            total=total,
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
