"""Projection for workflow execution list view.

This projection maintains a list of workflow executions (runs),
updated by WorkflowExecutionStarted, PhaseCompleted, WorkflowCompleted,
and WorkflowFailed events from the WorkflowExecutionAggregate.

Uses AutoDispatchProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)


class WorkflowExecutionListProjection(AutoDispatchProjection):
    """Builds workflow execution list read model from events.

    This projection maintains execution summaries for listing runs
    of workflow templates. Each execution is keyed by execution_id.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = "workflow_executions"
    VERSION = 4  # Bumped: resilient on_workflow_failed for orphaned failure events (#598)

    def __init__(self, store: ProjectionStoreProtocol):
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
        # Clear all workflow execution summaries
        # This depends on the store implementation supporting delete_all
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    async def on_workflow_execution_started(self, event_data: dict) -> None:
        """Handle WorkflowExecutionStarted event.

        Creates a new execution summary when an execution begins.
        """
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        # Extract repos from inputs field (ADR-058: stored as comma-separated string)
        repos_raw = event_data.get("inputs", {}).get("repos", "")
        repos = (
            tuple(u.strip() for u in str(repos_raw).split(",") if u.strip()) if repos_raw else ()
        )

        summary = WorkflowExecutionSummary(
            workflow_execution_id=execution_id,
            workflow_id=event_data.get("workflow_id", ""),
            workflow_name=event_data.get("workflow_name", ""),
            status="running",
            started_at=event_data.get("started_at"),
            completed_at=None,
            completed_phases=0,
            total_phases=event_data.get("total_phases", 0),
            total_tokens=0,
            total_cost_usd="0",
            tool_call_count=0,
            expected_completion_at=event_data.get("expected_completion_at"),
            repos=repos,
        )
        await self._store.save(self.PROJECTION_NAME, execution_id, summary.to_dict())

    async def on_phase_completed(self, event_data: dict) -> None:
        """Handle PhaseCompleted event.

        Updates completed phase count, token metrics, and tool call count.
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

            # Add tool calls from this phase
            phase_tool_calls = event_data.get("tool_call_count", 0)
            existing["tool_call_count"] = existing.get("tool_call_count", 0) + phase_tool_calls

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
        if not existing:
            # Create minimal entry for orphaned failure events (#598)
            existing = WorkflowExecutionSummary(
                workflow_execution_id=execution_id,
                workflow_id=event_data.get("workflow_id", ""),
                workflow_name=event_data.get("workflow_name", ""),
                status="failed",
                started_at=event_data.get("started_at"),
                completed_at=event_data.get("failed_at"),
                completed_phases=event_data.get("completed_phases", 0),
                total_phases=event_data.get("total_phases", 0),
                total_tokens=event_data.get("total_tokens", 0),
                total_cost_usd=event_data.get("total_cost_usd", "0"),
                tool_call_count=0,
                error_message=event_data.get("error_message"),
            ).to_dict()
        else:
            existing["status"] = "failed"
            existing["completed_at"] = event_data.get("failed_at")
            existing["error_message"] = event_data.get("error_message")
            existing["completed_phases"] = event_data.get(
                "completed_phases", existing.get("completed_phases", 0)
            )

        await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_execution_cancelled(self, event_data: dict) -> None:
        """Handle ExecutionCancelled event.

        Marks execution as cancelled via control plane.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if existing:
            existing["status"] = "cancelled"
            existing["completed_at"] = event_data.get("cancelled_at")
            await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_workflow_interrupted(self, event_data: dict) -> None:
        """Handle WorkflowInterrupted event.

        Marks execution as interrupted (forceful stop via SIGINT).
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if existing:
            existing["status"] = "interrupted"
            existing["completed_at"] = event_data.get("interrupted_at")
            existing["error_message"] = event_data.get("reason") or "Interrupted by user"
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

        # get_all returns a list, not a dict
        for data in all_data:
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

    async def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
        status_filter: str | None = None,
    ) -> list[WorkflowExecutionSummary]:
        """Get all executions with optional filtering.

        Args:
            limit: Maximum number of results.
            offset: Number of results to skip.
            status_filter: Optional status to filter by.

        Returns:
            List of execution summaries sorted by started_at descending.
        """
        all_data = await self._store.get_all(self.PROJECTION_NAME)
        executions = []

        for data in all_data:
            if status_filter and data.get("status") != status_filter:
                continue
            executions.append(WorkflowExecutionSummary.from_dict(data))

        # Sort by started_at descending (most recent first)
        executions.sort(key=lambda e: e.started_at or "", reverse=True)

        # Apply pagination
        return executions[offset : offset + limit]
