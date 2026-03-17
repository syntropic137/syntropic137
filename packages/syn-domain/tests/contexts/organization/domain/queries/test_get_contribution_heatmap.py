"""Validation tests for GetContributionHeatmapQuery."""

from __future__ import annotations

from datetime import date

import pytest

from syn_domain.contexts.organization.domain.queries.get_contribution_heatmap import (
    GetContributionHeatmapQuery,
)


@pytest.mark.unit
class TestGetContributionHeatmapQuery:
    def test_defaults(self) -> None:
        q = GetContributionHeatmapQuery()
        assert q.metric == "sessions"
        assert q.query_id
        assert (q.end_date - q.start_date).days == 365

    def test_invalid_metric_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid metric"):
            GetContributionHeatmapQuery(metric="invalid")

    def test_start_after_end_raises(self) -> None:
        with pytest.raises(ValueError, match="start_date must not be after end_date"):
            GetContributionHeatmapQuery(
                start_date=date(2026, 3, 15),
                end_date=date(2026, 3, 1),
            )

    def test_valid_metrics(self) -> None:
        for m in ("sessions", "executions", "commits", "cost_usd", "tokens"):
            q = GetContributionHeatmapQuery(metric=m)
            assert q.metric == m

    def test_filter_params(self) -> None:
        q = GetContributionHeatmapQuery(
            organization_id="org-1",
            system_id="sys-1",
            repo_id="repo-1",
        )
        assert q.organization_id == "org-1"
        assert q.system_id == "sys-1"
        assert q.repo_id == "repo-1"
