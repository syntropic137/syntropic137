"""Tests for get_metrics query slice."""

import os
from decimal import Decimal

import pytest

# Ensure test environment before any imports
os.environ["APP_ENVIRONMENT"] = "test"

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.queries.get_dashboard_metrics import (
    GetDashboardMetricsQuery,
)
from syn_domain.contexts.orchestration.slices.dashboard_metrics.GetDashboardMetricsHandler import (
    GetDashboardMetricsHandler,
)
from syn_domain.contexts.orchestration.slices.dashboard_metrics.projection import (
    DashboardMetricsProjection,
)


@pytest.fixture
def memory_store() -> InMemoryProjectionStore:
    """Create a fresh in-memory store for tests."""
    return InMemoryProjectionStore()


@pytest.fixture
def projection(memory_store: InMemoryProjectionStore) -> DashboardMetricsProjection:
    """Create projection with test store."""
    return DashboardMetricsProjection(memory_store)


@pytest.fixture
def handler(projection: DashboardMetricsProjection) -> GetDashboardMetricsHandler:
    """Create handler with test projection."""
    return GetDashboardMetricsHandler(projection)


@pytest.mark.unit
class TestDashboardMetricsProjection:
    """Tests for DashboardMetricsProjection."""

    @pytest.mark.asyncio
    async def test_initial_metrics_are_zero(self, projection: DashboardMetricsProjection):
        """Test that initial metrics are all zero."""
        metrics = await projection.get_metrics()
        assert metrics.total_workflows == 0
        assert metrics.active_workflows == 0
        assert metrics.completed_workflows == 0
        assert metrics.total_sessions == 0
        assert metrics.total_artifacts == 0

    @pytest.mark.asyncio
    async def test_workflow_created_increments_total(self, projection: DashboardMetricsProjection):
        """Test WorkflowCreated increments total_workflows."""
        await projection.on_workflow_template_created({"workflow_id": "wf-1"})
        await projection.on_workflow_template_created({"workflow_id": "wf-2"})

        metrics = await projection.get_metrics()
        assert metrics.total_workflows == 2

    @pytest.mark.asyncio
    async def test_workflow_lifecycle(self, projection: DashboardMetricsProjection):
        """Test full workflow lifecycle updates metrics correctly."""
        # Create workflow
        await projection.on_workflow_template_created({"workflow_id": "wf-1"})
        metrics = await projection.get_metrics()
        assert metrics.total_workflows == 1
        assert metrics.active_workflows == 0

        # Start execution
        await projection.on_workflow_execution_started({"workflow_id": "wf-1"})
        metrics = await projection.get_metrics()
        assert metrics.active_workflows == 1

        # Complete workflow
        await projection.on_workflow_completed({"workflow_id": "wf-1"})
        metrics = await projection.get_metrics()
        assert metrics.active_workflows == 0
        assert metrics.completed_workflows == 1

    @pytest.mark.asyncio
    async def test_workflow_failed_updates_counts(self, projection: DashboardMetricsProjection):
        """Test WorkflowFailed updates counts correctly."""
        await projection.on_workflow_template_created({"workflow_id": "wf-1"})
        await projection.on_workflow_execution_started({"workflow_id": "wf-1"})
        await projection.on_workflow_failed(
            {"workflow_id": "wf-1", "error": "Something went wrong"}
        )

        metrics = await projection.get_metrics()
        assert metrics.active_workflows == 0
        assert metrics.failed_workflows == 1

    @pytest.mark.asyncio
    async def test_session_events_update_metrics(self, projection: DashboardMetricsProjection):
        """Test session events update metrics."""
        await projection.on_session_started({"session_id": "s-1"})
        metrics = await projection.get_metrics()
        assert metrics.total_sessions == 1

        await projection.on_session_completed(
            {"session_id": "s-1", "total_tokens": 1000, "total_cost_usd": "0.05"}
        )
        metrics = await projection.get_metrics()
        assert metrics.total_tokens == 1000
        assert metrics.total_cost_usd == Decimal("0.05")

    @pytest.mark.asyncio
    async def test_artifact_created_increments_count(self, projection: DashboardMetricsProjection):
        """Test ArtifactCreated increments artifact count."""
        await projection.on_artifact_created({"artifact_id": "a-1"})
        await projection.on_artifact_created({"artifact_id": "a-2"})

        metrics = await projection.get_metrics()
        assert metrics.total_artifacts == 2

    @pytest.mark.asyncio
    async def test_cost_accumulation(self, projection: DashboardMetricsProjection):
        """Test that costs accumulate correctly across sessions."""
        await projection.on_session_started({"session_id": "s-1"})
        await projection.on_session_completed(
            {"session_id": "s-1", "total_tokens": 500, "total_cost_usd": "0.025"}
        )

        await projection.on_session_started({"session_id": "s-2"})
        await projection.on_session_completed(
            {"session_id": "s-2", "total_tokens": 1500, "total_cost_usd": "0.075"}
        )

        metrics = await projection.get_metrics()
        assert metrics.total_tokens == 2000
        assert metrics.total_cost_usd == Decimal("0.1")

    @pytest.mark.asyncio
    async def test_input_output_token_tracking(self, projection: DashboardMetricsProjection):
        """Test that input/output tokens are tracked separately."""
        await projection.on_session_started({"session_id": "s-1"})
        await projection.on_session_completed(
            {
                "session_id": "s-1",
                "total_tokens": 2500,
                "total_input_tokens": 1000,
                "total_output_tokens": 1500,
                "total_cost_usd": "0.025",
            }
        )

        await projection.on_session_started({"session_id": "s-2"})
        await projection.on_session_completed(
            {
                "session_id": "s-2",
                "total_tokens": 3500,
                "total_input_tokens": 1500,
                "total_output_tokens": 2000,
                "total_cost_usd": "0.035",
            }
        )

        metrics = await projection.get_metrics()
        assert metrics.total_tokens == 6000
        assert metrics.total_input_tokens == 2500
        assert metrics.total_output_tokens == 3500

    @pytest.mark.asyncio
    async def test_input_output_tokens_default_to_zero(
        self, projection: DashboardMetricsProjection
    ):
        """Test that input/output tokens default to zero when not provided."""
        await projection.on_session_started({"session_id": "s-1"})
        await projection.on_session_completed(
            {
                "session_id": "s-1",
                "total_tokens": 1000,
                "total_cost_usd": "0.01",
                # No input/output breakdown provided
            }
        )

        metrics = await projection.get_metrics()
        assert metrics.total_tokens == 1000
        assert metrics.total_input_tokens == 0
        assert metrics.total_output_tokens == 0


class TestGetDashboardMetricsHandler:
    """Tests for GetDashboardMetricsHandler."""

    @pytest.mark.asyncio
    async def test_handler_returns_metrics(
        self,
        projection: DashboardMetricsProjection,
        handler: GetDashboardMetricsHandler,
    ):
        """Test handler returns metrics correctly."""
        # Setup some data
        await projection.on_workflow_template_created({"workflow_id": "wf-1"})
        await projection.on_session_started({"session_id": "s-1"})
        await projection.on_artifact_created({"artifact_id": "a-1"})

        # Execute query
        query = GetDashboardMetricsQuery()
        result = await handler.handle(query)

        # Assert
        assert result.total_workflows == 1
        assert result.total_sessions == 1
        assert result.total_artifacts == 1
