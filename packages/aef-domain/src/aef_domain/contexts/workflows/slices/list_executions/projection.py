"""Projection for workflow execution list view.

This projection maintains a list of workflow executions (runs),
updated by WorkflowExecutionStarted, PhaseCompleted, WorkflowCompleted,
and WorkflowFailed events from the WorkflowExecutionAggregate.
"""

from typing import Any

from aef_domain.contexts.workflows.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)


class WorkflowExecutionListProjection:
    """Builds workflow execution list read model from events.

    This projection maintains execution summaries for listing runs
    of workflow templates. Each execution is keyed by execution_id.
    """

    PROJECTION_NAME = "workflow_executions"

    def __init__(self, store: Any):  # Using Any to avoid circular import
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_workflow_execution_started(self, event_data: dict) -> None:
        """Handle WorkflowExecutionStarted event.

        Creates a new execution summary when an execution begins.
        """
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        summary = WorkflowExecutionSummary(
            execution_id=execution_id,
            workflow_id=event_data.get("workflow_id", ""),
            workflow_name=event_data.get("workflow_name", ""),
            status="running",
            started_at=event_data.get("started_at"),
            completed_at=None,
            completed_phases=0,
            total_phases=event_data.get("total_phases", 0),
            total_tokens=0,
            total_cost_usd="0",
        )
        await self._store.save(self.PROJECTION_NAME, execution_id, summary.to_dict())

    async def on_phase_completed(self, event_data: dict) -> None:
        """Handle PhaseCompleted event.

        Updates completed phase count and token metrics.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if existing:
            # Increment completed phases
            existing["completed_phases"] = existing.get("completed_phases", 0) + 1

            # Add tokens from this phase
            phase_tokens = event_data.get("total_tokens", 0)
            existing["total_tokens"] = existing.get("total_tokens", 0) + phase_tokens

            # Add cost from this phase
            from decimal import Decimal

            phase_cost = Decimal(str(event_data.get("cost_usd", "0")))
            existing_cost = Decimal(str(existing.get("total_cost_usd", "0")))
            existing["total_cost_usd"] = str(existing_cost + phase_cost)

            await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_workflow_completed(self, event_data: dict) -> None:
        """Handle WorkflowCompleted event.

        Marks execution as completed with final metrics.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if existing:
            existing["status"] = "completed"
            existing["completed_at"] = event_data.get("completed_at")
            existing["completed_phases"] = event_data.get(
                "completed_phases", existing.get("completed_phases", 0)
            )
            existing["total_tokens"] = event_data.get(
                "total_tokens", existing.get("total_tokens", 0)
            )

            # Update cost if provided
            if "total_cost_usd" in event_data:
                existing["total_cost_usd"] = str(event_data.get("total_cost_usd", "0"))

            await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Handle WorkflowFailed event.

        Marks execution as failed with error information.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if existing:
            existing["status"] = "failed"
            existing["completed_at"] = event_data.get("failed_at")
            existing["error_message"] = event_data.get("error_message")
            existing["completed_phases"] = event_data.get(
                "completed_phases", existing.get("completed_phases", 0)
            )

            await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def get_by_workflow_id(self, workflow_id: str) -> list[WorkflowExecutionSummary]:
        """Get all executions for a workflow.

        Args:
            workflow_id: The workflow template ID.

        Returns:
            List of execution summaries for this workflow.
        """
        all_data = await self._store.get_all(self.PROJECTION_NAME)
        executions = []

        for data in all_data.values():
            if data.get("workflow_id") == workflow_id:
                executions.append(WorkflowExecutionSummary.from_dict(data))

        # Sort by started_at descending (most recent first)
        executions.sort(key=lambda e: e.started_at or "", reverse=True)
        return executions

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionSummary | None:
        """Get a specific execution by ID.

        Args:
            execution_id: The execution ID.

        Returns:
            Execution summary or None if not found.
        """
        data = await self._store.get(self.PROJECTION_NAME, execution_id)
        if data:
            return WorkflowExecutionSummary.from_dict(data)
        return None
