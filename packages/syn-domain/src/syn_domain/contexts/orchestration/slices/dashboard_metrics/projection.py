"""Projection for dashboard metrics.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from decimal import Decimal
from typing import Any

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.domain.read_models.dashboard_metrics import (
    DashboardMetrics,
)


class DashboardMetricsProjection(AutoDispatchProjection):
    """Builds dashboard metrics read model from events.

    This projection aggregates data from workflow, session, and artifact
    events to maintain a summary view of system metrics.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "dashboard_metrics"
    METRICS_KEY = "global"  # Single record for global metrics
    VERSION = 2  # Bumped: migrated to AutoDispatchProjection, renamed on_workflow_created

    def __init__(self, store: Any):  # Using Any to avoid circular import
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version - increment to trigger rebuild."""
        return self.VERSION

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    async def _get_or_create_metrics(self) -> dict:
        """Get existing metrics or create empty ones."""
        existing = await self._store.get(self.PROJECTION_NAME, self.METRICS_KEY)
        if existing:
            return existing
        # Initialize with empty metrics
        return DashboardMetrics().to_dict()

    async def _save_metrics(self, metrics: dict) -> None:
        """Save metrics to store."""
        await self._store.save(self.PROJECTION_NAME, self.METRICS_KEY, metrics)

    async def on_workflow_template_created(self, _event_data: dict) -> None:
        """Handle WorkflowTemplateCreated event - increment total workflows."""
        metrics = await self._get_or_create_metrics()
        metrics["total_workflows"] = metrics.get("total_workflows", 0) + 1
        await self._save_metrics(metrics)

    async def on_workflow_execution_started(self, _event_data: dict) -> None:
        """Handle WorkflowExecutionStarted - increment active workflows."""
        metrics = await self._get_or_create_metrics()
        metrics["active_workflows"] = metrics.get("active_workflows", 0) + 1
        await self._save_metrics(metrics)

    async def on_phase_started(self, _event_data: dict) -> None:
        """Handle PhaseStarted - increment active if first phase."""
        # Only increment if this is the first phase starting
        # We track this via the workflow status change
        pass

    async def on_workflow_completed(self, _event_data: dict) -> None:
        """Handle WorkflowCompleted - update workflow counts."""
        metrics = await self._get_or_create_metrics()
        metrics["active_workflows"] = max(0, metrics.get("active_workflows", 0) - 1)
        metrics["completed_workflows"] = metrics.get("completed_workflows", 0) + 1
        await self._save_metrics(metrics)

    async def on_workflow_failed(self, _event_data: dict) -> None:
        """Handle WorkflowFailed - update workflow counts."""
        metrics = await self._get_or_create_metrics()
        metrics["active_workflows"] = max(0, metrics.get("active_workflows", 0) - 1)
        metrics["failed_workflows"] = metrics.get("failed_workflows", 0) + 1
        await self._save_metrics(metrics)

    async def on_session_started(self, _event_data: dict) -> None:
        """Handle SessionStarted - increment session count."""
        metrics = await self._get_or_create_metrics()
        metrics["total_sessions"] = metrics.get("total_sessions", 0) + 1
        await self._save_metrics(metrics)

    async def on_session_completed(self, event_data: dict) -> None:
        """Handle SessionCompleted - update token and cost totals."""
        metrics = await self._get_or_create_metrics()

        # Add total tokens from this session
        metrics["total_tokens"] = metrics.get("total_tokens", 0) + event_data.get("total_tokens", 0)

        # Add input/output token breakdown
        metrics["total_input_tokens"] = metrics.get("total_input_tokens", 0) + event_data.get(
            "total_input_tokens", 0
        )
        metrics["total_output_tokens"] = metrics.get("total_output_tokens", 0) + event_data.get(
            "total_output_tokens", 0
        )

        # Add cost from this session
        existing_cost = Decimal(str(metrics.get("total_cost_usd", 0)))
        session_cost = Decimal(str(event_data.get("total_cost_usd", 0)))
        metrics["total_cost_usd"] = str(existing_cost + session_cost)

        await self._save_metrics(metrics)

    async def on_artifact_created(self, _event_data: dict) -> None:
        """Handle ArtifactCreated - increment artifact count."""
        metrics = await self._get_or_create_metrics()
        metrics["total_artifacts"] = metrics.get("total_artifacts", 0) + 1
        await self._save_metrics(metrics)

    async def get_metrics(self) -> DashboardMetrics:
        """Get the current dashboard metrics."""
        data = await self._get_or_create_metrics()
        return DashboardMetrics.from_dict(data)
