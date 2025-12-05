"""Projection for workflow TEMPLATE detail view.

This projection maintains workflow TEMPLATE (definition) details.
For execution details, see WorkflowExecutionDetailProjection.
"""

from typing import Any

from aef_domain.contexts.workflows.domain.read_models.workflow_detail import (
    PhaseDefinitionDetail,
    WorkflowDetail,
)


class WorkflowDetailProjection:
    """Builds workflow TEMPLATE detail read model from events.

    Templates don't have execution status. They only track:
    - Definition info (name, type, phases)
    - runs_count (how many times executed)

    For execution status, see WorkflowExecutionDetailProjection.
    """

    PROJECTION_NAME = "workflow_details"

    def __init__(self, store: Any):
        """Initialize with a projection store."""
        self._store = store

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_workflow_created(self, event_data: dict) -> None:
        """Handle WorkflowCreated event - create template detail."""
        workflow_id = event_data.get("workflow_id", "")

        # Convert phase data to PhaseDefinitionDetail format
        phases_data = event_data.get("phases", [])
        phases = [
            PhaseDefinitionDetail(
                id=p.get("id", p.get("phase_id", f"phase-{i}")),
                name=p.get("name", ""),
                description=p.get("description"),
                agent_type=p.get("agent_type", ""),
                order=p.get("order", i),
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
