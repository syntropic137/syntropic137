"""Projection for dashboard metrics.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateArchivedEvent import (
    WorkflowTemplateArchivedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateUpdatedEvent import (
    WorkflowTemplateUpdatedEvent,
)
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
    VERSION = 5  # Bumped: total_workflows excludes archived templates (#641)
    ARCHIVED_KEY_PREFIX = "archived:"  # One marker record per archived template

    def __init__(self, store: ProjectionStore):
        """Initialize with a projection store.

        Args:
            store: A ProjectionStore implementation
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
        """Handle WorkflowTemplateCreated event - count the new template."""
        metrics = await self._get_or_create_metrics()
        metrics["total_workflows"] = metrics.get("total_workflows", 0) + 1
        await self._save_metrics(metrics)

    async def on_workflow_template_archived(
        self, event_data: WorkflowTemplateArchivedEvent
    ) -> None:
        """Handle WorkflowTemplateArchived - stop counting the template.

        total_workflows matches GET /workflows, which hides archived templates.
        The marker remembers the archive so a later reinstall can count the
        template again, and makes a repeated archive a no-op.
        """
        workflow_id = WorkflowTemplateArchivedEvent.model_validate(event_data).workflow_id
        if await self._is_archived(workflow_id):
            return
        await self._store.save(
            self.PROJECTION_NAME, self._archived_key(workflow_id), {"workflow_id": workflow_id}
        )
        metrics = await self._get_or_create_metrics()
        metrics["total_workflows"] = max(0, metrics.get("total_workflows", 0) - 1)
        await self._save_metrics(metrics)

    async def on_workflow_template_updated(self, event_data: WorkflowTemplateUpdatedEvent) -> None:
        """Handle WorkflowTemplateUpdated - count a reinstalled archived template again.

        A reinstall emits Updated and clears the archived flag (#822). An update
        to a template that was never archived is not a new template, so it
        leaves the count alone.
        """
        workflow_id = WorkflowTemplateUpdatedEvent.model_validate(event_data).workflow_id
        if not await self._is_archived(workflow_id):
            return
        await self._store.delete(self.PROJECTION_NAME, self._archived_key(workflow_id))
        metrics = await self._get_or_create_metrics()
        metrics["total_workflows"] = metrics.get("total_workflows", 0) + 1
        await self._save_metrics(metrics)

    def _archived_key(self, workflow_id: str) -> str:
        return f"{self.ARCHIVED_KEY_PREFIX}{workflow_id}"

    async def _is_archived(self, workflow_id: str) -> bool:
        return (
            await self._store.get(self.PROJECTION_NAME, self._archived_key(workflow_id)) is not None
        )

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

        # Add input/output/cache token breakdown
        metrics["total_input_tokens"] = metrics.get("total_input_tokens", 0) + event_data.get(
            "total_input_tokens", 0
        )
        metrics["total_output_tokens"] = metrics.get("total_output_tokens", 0) + event_data.get(
            "total_output_tokens", 0
        )
        metrics["total_cache_creation_tokens"] = metrics.get(
            "total_cache_creation_tokens", 0
        ) + event_data.get("total_cache_creation_tokens", 0)
        metrics["total_cache_read_tokens"] = metrics.get(
            "total_cache_read_tokens", 0
        ) + event_data.get("total_cache_read_tokens", 0)

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
