"""Tests for GetSystemPatternsHandler."""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_domain.contexts.organization._shared.projection_names import WORKFLOW_EXECUTIONS
from syn_domain.contexts.organization.domain.queries.get_system_patterns import (
    GetSystemPatternsQuery,
)
from syn_domain.contexts.organization.slices.conftest import (
    FakeProjectionStore,
    _make_projections,
)
from syn_domain.contexts.organization.domain.read_models.system_patterns import FailurePattern
from syn_domain.contexts.organization.slices.system_patterns.GetSystemPatternsHandler import (
    GetSystemPatternsHandler,
    _accumulate_failure,
    _groups_to_patterns,
)


@pytest.mark.unit
class TestGetSystemPatternsHandler:
    @pytest.mark.asyncio
    async def test_groups_failures_by_error(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemPatternsHandler(store, sys_proj, repo_proj)

        # Correlate two executions
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

        # Two failed executions with same error
        await store.save(
            WORKFLOW_EXECUTIONS,
            "exec-1",
            {
                "workflow_execution_id": "exec-1",
                "status": "failed",
                "error_type": "timeout",
                "error_message": "Timed out after 300s",
                "completed_at": "2026-03-06T10:00:00",
            },
        )
        await store.save(
            WORKFLOW_EXECUTIONS,
            "exec-2",
            {
                "workflow_execution_id": "exec-2",
                "status": "failed",
                "error_type": "timeout",
                "error_message": "Timed out after 300s",
                "completed_at": "2026-03-06T11:00:00",
            },
        )

        result = await handler.handle(GetSystemPatternsQuery(system_id="sys-1"))

        assert len(result.failure_patterns) == 1
        assert result.failure_patterns[0].error_type == "timeout"
        assert result.failure_patterns[0].occurrence_count == 2
        assert "acme/api" in result.failure_patterns[0].affected_repos

    @pytest.mark.asyncio
    async def test_detects_cost_outliers(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _make_projections(
            "sys-1", "Backend", "org-1", ["acme/api", "acme/worker", "acme/web"]
        )
        handler = GetSystemPatternsHandler(store, sys_proj, repo_proj)

        # acme/api costs 100x more than others
        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "100.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )
        await store.save(
            "repo_cost",
            "acme/worker",
            {
                "total_cost_usd": "1.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )
        await store.save(
            "repo_cost",
            "acme/web",
            {
                "total_cost_usd": "1.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )

        result = await handler.handle(GetSystemPatternsQuery(system_id="sys-1"))

        assert len(result.cost_outliers) == 1
        assert result.cost_outliers[0].repo_full_name == "acme/api"
        assert result.cost_outliers[0].cost_usd == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self) -> None:
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _make_projections("sys-1", "Backend", "org-1", [])
        handler = GetSystemPatternsHandler(store, sys_proj, repo_proj)

        result = await handler.handle(GetSystemPatternsQuery(system_id="sys-1"))

        assert len(result.failure_patterns) == 0
        assert len(result.cost_outliers) == 0

    @pytest.mark.asyncio
    async def test_boundary_factor_3x(self) -> None:
        """Exactly 3x median should NOT be an outlier (>3x required)."""
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _make_projections(
            "sys-1", "Backend", "org-1", ["acme/api", "acme/worker"]
        )
        handler = GetSystemPatternsHandler(store, sys_proj, repo_proj)

        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "3.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )
        await store.save(
            "repo_cost",
            "acme/worker",
            {
                "total_cost_usd": "1.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )

        result = await handler.handle(GetSystemPatternsQuery(system_id="sys-1"))

        # median=2.00, factor=3.00/2.00=1.5 — not an outlier
        assert len(result.cost_outliers) == 0

    @pytest.mark.asyncio
    async def test_single_repo_no_outliers(self) -> None:
        """A single repo cannot be an outlier (need at least 2)."""
        store = FakeProjectionStore()
        sys_proj, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
        handler = GetSystemPatternsHandler(store, sys_proj, repo_proj)

        await store.save(
            "repo_cost",
            "acme/api",
            {
                "total_cost_usd": "100.00",
                "total_tokens": 0,
                "execution_count": 1,
            },
        )

        result = await handler.handle(GetSystemPatternsQuery(system_id="sys-1"))

        assert len(result.cost_outliers) == 0


@pytest.mark.unit
class TestAccumulateFailure:
    def test_first_occurrence_creates_group(self) -> None:
        groups: dict = {}
        _accumulate_failure(
            groups,
            {"error_type": "timeout", "error_message": "Timed out", "completed_at": "2026-01-01T00:00:00"},
            "acme/api",
        )
        assert len(groups) == 1
        key = ("timeout", "Timed out")
        assert groups[key]["count"] == 1
        assert "acme/api" in groups[key]["repos"]

    def test_duplicate_increments_count(self) -> None:
        groups: dict = {}
        execution = {"error_type": "timeout", "error_message": "Timed out", "completed_at": "2026-01-01"}
        _accumulate_failure(groups, execution, "acme/api")
        _accumulate_failure(groups, execution, "acme/worker")
        key = ("timeout", "Timed out")
        assert groups[key]["count"] == 2
        assert groups[key]["repos"] == {"acme/api", "acme/worker"}

    def test_repos_deduplicated(self) -> None:
        groups: dict = {}
        execution = {"error_type": "timeout", "error_message": "Timed out"}
        _accumulate_failure(groups, execution, "acme/api")
        _accumulate_failure(groups, execution, "acme/api")
        key = ("timeout", "Timed out")
        assert groups[key]["count"] == 2
        assert len(groups[key]["repos"]) == 1

    def test_timestamps_track_range(self) -> None:
        groups: dict = {}
        _accumulate_failure(
            groups,
            {"error_type": "e", "error_message": "m", "completed_at": "2026-01-05"},
            "r1",
        )
        _accumulate_failure(
            groups,
            {"error_type": "e", "error_message": "m", "completed_at": "2026-01-01"},
            "r2",
        )
        _accumulate_failure(
            groups,
            {"error_type": "e", "error_message": "m", "completed_at": "2026-01-10"},
            "r3",
        )
        g = groups[("e", "m")]
        assert g["first_seen"] == "2026-01-01"
        assert g["last_seen"] == "2026-01-10"

    def test_missing_fields_default_to_empty(self) -> None:
        groups: dict = {}
        _accumulate_failure(groups, {}, "")
        key = ("", "")
        assert groups[key]["count"] == 1
        assert len(groups[key]["repos"]) == 0


@pytest.mark.unit
class TestGroupsToPatterns:
    def test_empty_groups(self) -> None:
        assert _groups_to_patterns({}) == []

    def test_sorted_by_count_descending(self) -> None:
        groups = {
            ("e1", "m1"): {"error_type": "e1", "error_message": "m1", "count": 5, "repos": set(), "first_seen": "", "last_seen": ""},
            ("e2", "m2"): {"error_type": "e2", "error_message": "m2", "count": 10, "repos": set(), "first_seen": "", "last_seen": ""},
            ("e3", "m3"): {"error_type": "e3", "error_message": "m3", "count": 1, "repos": set(), "first_seen": "", "last_seen": ""},
        }
        result = _groups_to_patterns(groups)
        assert [p.occurrence_count for p in result] == [10, 5, 1]

    def test_repos_alphabetically_sorted(self) -> None:
        groups = {
            ("e", "m"): {"error_type": "e", "error_message": "m", "count": 1, "repos": {"z-repo", "a-repo", "m-repo"}, "first_seen": "", "last_seen": ""},
        }
        result = _groups_to_patterns(groups)
        assert result[0].affected_repos == ["a-repo", "m-repo", "z-repo"]

    def test_all_fields_mapped(self) -> None:
        groups = {
            ("timeout", "Timed out"): {
                "error_type": "timeout", "error_message": "Timed out",
                "count": 3, "repos": {"acme/api"},
                "first_seen": "2026-01-01", "last_seen": "2026-01-10",
            },
        }
        result = _groups_to_patterns(groups)
        p = result[0]
        assert isinstance(p, FailurePattern)
        assert p.error_type == "timeout"
        assert p.error_message == "Timed out"
        assert p.occurrence_count == 3
        assert p.first_seen == "2026-01-01"
        assert p.last_seen == "2026-01-10"
