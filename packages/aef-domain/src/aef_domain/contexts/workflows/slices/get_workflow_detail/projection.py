"""Projection for workflow TEMPLATE detail view.

This projection maintains workflow TEMPLATE (definition) details.
For execution details, see WorkflowExecutionDetailProjection.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from datetime import UTC, datetime
from typing import Any

from event_sourcing import (
    CheckpointedProjection,
    EventEnvelope,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

from aef_domain.contexts.workflows.domain.constants import (
    PhaseDefaults,
    PhaseFields,
)
from aef_domain.contexts.workflows.domain.read_models.workflow_detail import (
    PhaseDefinitionDetail,
    WorkflowDetail,
)

# Event types this projection subscribes to
_SUBSCRIBED_EVENTS = {
    "WorkflowCreated",
    "WorkflowExecutionStarted",  # To increment runs_count
}


class WorkflowDetailProjection(CheckpointedProjection):
    """Builds workflow TEMPLATE detail read model from events.

    Templates don't have execution status. They only track:
    - Definition info (name, type, phases)
    - runs_count (how many times executed)

    For execution status, see WorkflowExecutionDetailProjection.

    Implements CheckpointedProjection for per-projection position tracking.
    """

    PROJECTION_NAME = "workflow_details"
    VERSION = 1

    def __init__(self, store: Any):
        """Initialize with a projection store."""
        self._store = store

    # === CheckpointedProjection required methods ===

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version - increment to trigger rebuild."""
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        """Event types this projection handles."""
        return _SUBSCRIBED_EVENTS

    async def handle_event(
        self,
        envelope: EventEnvelope[Any],
        checkpoint_store: ProjectionCheckpointStore,
    ) -> ProjectionResult:
        """Handle an event and save checkpoint atomically."""
        event_type = envelope.event.event_type
        event_data = envelope.event.model_dump()
        global_nonce = envelope.metadata.global_nonce or 0

        try:
            if event_type == "WorkflowCreated":
                await self.on_workflow_created(event_data)
            elif event_type == "WorkflowExecutionStarted":
                await self.on_workflow_execution_started(event_data)

            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=global_nonce,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS

        except Exception:
            return ProjectionResult.FAILURE

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    @property
    def name(self) -> str:
        """Get the projection name (deprecated, use get_name())."""
        return self.PROJECTION_NAME

    async def on_workflow_created(self, event_data: dict) -> None:
        """Handle WorkflowCreated event - create template detail."""
        workflow_id = event_data.get("workflow_id", "")

        # Convert phase data to PhaseDefinitionDetail format
        # Note: older events may use "prompt_template_id" instead of "prompt_template"
        phases_data = event_data.get("phases", [])
        phases = [
            PhaseDefinitionDetail(
                id=p.get(PhaseFields.ID, p.get(PhaseFields.PHASE_ID, f"phase-{i}")),
                name=p.get(PhaseFields.NAME, ""),
                description=p.get(PhaseFields.DESCRIPTION),
                agent_type=p.get(PhaseFields.AGENT_TYPE, PhaseDefaults.AGENT_TYPE),
                order=p.get(PhaseFields.ORDER, i),
                # Check both new and old field names for backwards compatibility
                prompt_template=p.get(PhaseFields.PROMPT_TEMPLATE)
                or p.get("prompt_template_id"),
                timeout_seconds=p.get(
                    PhaseFields.TIMEOUT_SECONDS, PhaseDefaults.TIMEOUT_SECONDS
                ),
                allowed_tools=tuple(p.get(PhaseFields.ALLOWED_TOOLS, [])),
            )
            for i, p in enumerate(phases_data)
        ]

        detail = WorkflowDetail(
            id=workflow_id,
            name=event_data.get("name", ""),
            workflow_type=event_data.get("workflow_type", ""),
            classification=event_data.get("classification", ""),
            description=event_data.get("description"),
            phases=phases,
            created_at=event_data.get("created_at"),
            runs_count=0,
        )
        await self._store.save(self.PROJECTION_NAME, workflow_id, detail.to_dict())

    async def on_workflow_execution_started(self, event_data: dict) -> None:
        """Handle WorkflowExecutionStarted - increment runs_count."""
        workflow_id = event_data.get("workflow_id")
        if not workflow_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if existing:
            existing["runs_count"] = existing.get("runs_count", 0) + 1
            await self._store.save(self.PROJECTION_NAME, workflow_id, existing)

    async def get_by_id(self, workflow_id: str) -> WorkflowDetail | None:
        """Get a workflow template by ID."""
        data = await self._store.get(self.PROJECTION_NAME, workflow_id)
        if data:
            return WorkflowDetail.from_dict(data)
        return None
