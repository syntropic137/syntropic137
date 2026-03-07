"""Round-trip tests for organization read models.

Verifies from_dict(to_dict(model)) == model for all new read models.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from syn_domain.contexts.organization.domain.read_models.global_overview import (
    GlobalOverview,
    SystemOverviewEntry,
)
from syn_domain.contexts.organization.domain.read_models.repo_activity import (
    RepoActivityEntry,
)
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost
from syn_domain.contexts.organization.domain.read_models.repo_execution_correlation import (
    RepoExecutionCorrelation,
)
from syn_domain.contexts.organization.domain.read_models.repo_failure import RepoFailure
from syn_domain.contexts.organization.domain.read_models.repo_health import RepoHealth
from syn_domain.contexts.organization.domain.read_models.system_cost import SystemCost
from syn_domain.contexts.organization.domain.read_models.system_patterns import (
    CostOutlier,
    FailurePattern,
    SystemPatterns,
)
from syn_domain.contexts.organization.domain.read_models.system_status import (
    RepoStatusEntry,
    SystemStatus,
)


@pytest.mark.unit
class TestReadModelRoundTrip:
    def test_repo_execution_correlation(self) -> None:
        model = RepoExecutionCorrelation(
            repo_full_name="acme/repo",
            repo_id="repo-123",
            execution_id="exec-456",
            workflow_id="wf-789",
            correlation_source="trigger",
            correlated_at="2026-03-06T10:00:00+00:00",
        )
        assert RepoExecutionCorrelation.from_dict(model.to_dict()) == model

    def test_repo_health(self) -> None:
        model = RepoHealth(
            repo_id="repo-1",
            repo_full_name="acme/api",
            total_executions=100,
            successful_executions=95,
            failed_executions=5,
            success_rate=0.95,
            trend="improving",
            window_cost_usd=Decimal("12.50"),
            window_tokens=50000,
            last_execution_at="2026-03-06T10:00:00",
        )
        assert RepoHealth.from_dict(model.to_dict()) == model

    def test_repo_activity_entry(self) -> None:
        model = RepoActivityEntry(
            execution_id="exec-1",
            workflow_id="wf-1",
            workflow_name="Deploy",
            status="completed",
            started_at="2026-03-06T10:00:00",
            completed_at="2026-03-06T10:05:00",
            duration_seconds=300.0,
            trigger_source="webhook",
        )
        assert RepoActivityEntry.from_dict(model.to_dict()) == model

    def test_repo_failure(self) -> None:
        model = RepoFailure(
            execution_id="exec-1",
            workflow_id="wf-1",
            workflow_name="Test",
            failed_at="2026-03-06T10:00:00",
            error_message="Container crashed",
            error_type="crash",
            phase_name="build",
            conversation_tail=["line 1", "line 2"],
        )
        assert RepoFailure.from_dict(model.to_dict()) == model

    def test_repo_cost(self) -> None:
        model = RepoCost(
            repo_id="repo-1",
            repo_full_name="acme/api",
            total_cost_usd=Decimal("45.67"),
            total_tokens=200000,
            total_input_tokens=150000,
            total_output_tokens=50000,
            cost_by_workflow={"wf-1": Decimal("30.00"), "wf-2": Decimal("15.67")},
            cost_by_model={"claude-opus-4-6": Decimal("45.67")},
            execution_count=10,
        )
        assert RepoCost.from_dict(model.to_dict()) == model

    def test_system_status(self) -> None:
        model = SystemStatus(
            system_id="sys-1",
            system_name="Backend",
            organization_id="org-1",
            overall_status="degraded",
            total_repos=5,
            healthy_repos=3,
            degraded_repos=1,
            failing_repos=1,
            repos=[
                RepoStatusEntry(
                    repo_id="repo-1",
                    repo_full_name="acme/api",
                    status="healthy",
                    success_rate=0.98,
                    active_executions=1,
                    last_execution_at="2026-03-06T10:00:00",
                ),
            ],
        )
        assert SystemStatus.from_dict(model.to_dict()) == model

    def test_system_cost(self) -> None:
        model = SystemCost(
            system_id="sys-1",
            system_name="Backend",
            organization_id="org-1",
            total_cost_usd=Decimal("100.00"),
            total_tokens=500000,
            total_input_tokens=400000,
            total_output_tokens=100000,
            cost_by_repo={"acme/api": Decimal("60.00"), "acme/web": Decimal("40.00")},
            cost_by_workflow={"wf-1": Decimal("100.00")},
            cost_by_model={"claude-opus-4-6": Decimal("100.00")},
            execution_count=25,
        )
        assert SystemCost.from_dict(model.to_dict()) == model

    def test_system_patterns(self) -> None:
        model = SystemPatterns(
            system_id="sys-1",
            system_name="Backend",
            failure_patterns=[
                FailurePattern(
                    error_type="timeout",
                    error_message="Phase exceeded 600s timeout",
                    occurrence_count=3,
                    affected_repos=["acme/api", "acme/worker"],
                    first_seen="2026-03-01T00:00:00",
                    last_seen="2026-03-06T00:00:00",
                ),
            ],
            cost_outliers=[
                CostOutlier(
                    execution_id="exec-99",
                    repo_full_name="acme/api",
                    workflow_name="Deploy",
                    cost_usd=Decimal("25.00"),
                    median_cost_usd=Decimal("5.00"),
                    deviation_factor=4.0,
                    executed_at="2026-03-05T12:00:00",
                ),
            ],
            analysis_window_hours=168,
        )
        assert SystemPatterns.from_dict(model.to_dict()) == model

    def test_global_overview(self) -> None:
        model = GlobalOverview(
            total_systems=3,
            total_repos=15,
            unassigned_repos=2,
            total_active_executions=5,
            total_cost_usd=Decimal("500.00"),
            systems=[
                SystemOverviewEntry(
                    system_id="sys-1",
                    system_name="Backend",
                    organization_id="org-1",
                    organization_name="Acme",
                    repo_count=5,
                    overall_status="healthy",
                    active_executions=2,
                    total_cost_usd=Decimal("200.00"),
                ),
            ],
        )
        assert GlobalOverview.from_dict(model.to_dict()) == model
