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
    ArtifactCreatedRef,
    DashboardMetrics,
    TemplateCreatedRef,
)


class DashboardMetricsProjection(AutoDispatchProjection):
    """Builds dashboard metrics read model from events.

    Counts workflow templates and artifacts. Execution, session and token
    totals are not kept here: GET /metrics reads them from their own read
    models (#1843, #932, #2272).

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "dashboard_metrics"
    METRICS_KEY = "global"  # Single record for global metrics
    VERSION = 7  # Bumped: total_artifact_bytes sums ArtifactCreated.size_bytes (#2274)
    LIVE_TEMPLATES_KEY = "live_workflow_ids"  # In the global record; see total_workflows below

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

    # total_workflows mirrors GET /workflows' default total: the templates the
    # workflow_list projection shows and has not marked archived (#641). It is
    # kept as the set of those ids inside the one `global` record, so each event
    # is a single save (no partial write to lose on a retry) and every handler is
    # an idempotent set operation (a replayed event changes nothing). The same
    # events move a template in and out of both read models: Created and
    # Updated (a reinstall upserts and clears archived, #822) show it, Archived
    # hides it, and an Archived for a template never shown changes nothing.

    async def on_workflow_template_created(self, event_data: TemplateCreatedRef) -> None:
        """Handle WorkflowTemplateCreated - count the new template."""
        workflow_id = TemplateCreatedRef.model_validate(event_data).workflow_id
        if workflow_id:
            await self._update_live_templates(add=workflow_id)

    async def on_workflow_template_archived(
        self, event_data: WorkflowTemplateArchivedEvent
    ) -> None:
        """Handle WorkflowTemplateArchived - stop counting the template."""
        workflow_id = WorkflowTemplateArchivedEvent.model_validate(event_data).workflow_id
        await self._update_live_templates(remove=workflow_id)

    async def on_workflow_template_updated(self, event_data: WorkflowTemplateUpdatedEvent) -> None:
        """Handle WorkflowTemplateUpdated - a reinstall shows the template again."""
        workflow_id = WorkflowTemplateUpdatedEvent.model_validate(event_data).workflow_id
        await self._update_live_templates(add=workflow_id)

    async def _update_live_templates(self, *, add: str = "", remove: str = "") -> None:
        metrics = await self._get_or_create_metrics()
        live = set(metrics.get(self.LIVE_TEMPLATES_KEY, []))
        if add:
            live.add(add)
        if remove:
            live.discard(remove)
        metrics[self.LIVE_TEMPLATES_KEY] = sorted(live)
        metrics["total_workflows"] = len(live)
        await self._save_metrics(metrics)

    # Events stored before the rename (WorkflowTemplateAggregate still applies
    # them), so they reach the read model in production and tests alike (#2265).
    on_workflow_created = on_workflow_template_created

    async def on_artifact_created(self, event_data: ArtifactCreatedRef) -> None:
        """Handle ArtifactCreated - increment artifact count and byte total."""
        size_bytes = ArtifactCreatedRef.model_validate(event_data).size_bytes
        metrics = await self._get_or_create_metrics()
        metrics["total_artifacts"] = metrics.get("total_artifacts", 0) + 1
        metrics["total_artifact_bytes"] = metrics.get("total_artifact_bytes", 0) + size_bytes
        await self._save_metrics(metrics)

    async def get_metrics(self) -> DashboardMetrics:
        """Get the current dashboard metrics."""
        data = await self._get_or_create_metrics()
        return DashboardMetrics.from_dict(data)
