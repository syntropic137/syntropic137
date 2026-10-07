"""Projection for workflow execution list view.

This projection maintains a list of workflow executions (runs),
updated by WorkflowExecutionStarted, PhaseCompleted, WorkflowCompleted,
and WorkflowFailed events from the WorkflowExecutionAggregate.

Uses AutoDispatchProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import ProjectionStore

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration._shared.execution_list_reads import (
    WORKFLOW_EXECUTIONS,
    ExecutionListReads,
)
from syn_domain.contexts.orchestration._shared.tags import TagSet, replay_tag_edit
from syn_domain.contexts.orchestration._shared.unapplied_start import UnappliableStartError
from syn_domain.contexts.orchestration.domain.aggregate_execution.eval_membership import (
    AssociationKind,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    ReportedFailureReason,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionAttachedToEvalEvent import (
    ExecutionAttachedToEvalEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionDetachedFromEvalEvent import (
    ExecutionDetachedFromEvalEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionTagsAddedEvent import (
    ExecutionTagsAddedEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionTagsRemovedEvent import (
    ExecutionTagsRemovedEvent,
)
from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.projection_scan import read_by_keys


class WorkflowExecutionListProjection(ExecutionListReads, AutoDispatchProjection):
    """Builds workflow execution list read model from events.

    This projection maintains execution summaries for listing runs
    of workflow templates. Each execution is keyed by execution_id.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    The paged and tallied reads come from ExecutionListReads, which list_evals
    shares.
    """

    PROJECTION_NAME = WORKFLOW_EXECUTIONS
    VERSION = 8  # v8: eval_id and association_kind (#967)

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
            raise UnappliableStartError(self.PROJECTION_NAME)

        # Extract repos from inputs field (ADR-058: stored as comma-separated string)
        repos_raw = event_data.get("inputs", {}).get("repos", "")
        repos = (
            tuple(u.strip() for u in str(repos_raw).split(",") if u.strip()) if repos_raw else ()
        )

        launched_with = TagSet.recorded(event_data.get("tags") or []).values
        eval_id = event_data.get("eval_id")

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
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_creation_tokens=0,
            total_cache_read_tokens=0,
            tool_call_count=0,
            expected_completion_at=event_data.get("expected_completion_at"),
            repos=repos,
            tags=launched_with,
            inherited_tags=launched_with,
            eval_id=eval_id,
            association_kind=AssociationKind.LAUNCHED.value if eval_id else None,
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

            # Add tokens from this phase (all 4 components + total)
            existing["total_tokens"] = existing.get("total_tokens", 0) + event_data.get(
                "total_tokens", 0
            )
            existing["total_input_tokens"] = existing.get("total_input_tokens", 0) + event_data.get(
                "input_tokens", 0
            )
            existing["total_output_tokens"] = existing.get(
                "total_output_tokens", 0
            ) + event_data.get("output_tokens", 0)
            existing["total_cache_creation_tokens"] = existing.get(
                "total_cache_creation_tokens", 0
            ) + event_data.get("cache_creation_tokens", 0)
            existing["total_cache_read_tokens"] = existing.get(
                "total_cache_read_tokens", 0
            ) + event_data.get("cache_read_tokens", 0)

            # Add tool calls from this phase
            phase_tool_calls = event_data.get("tool_call_count", 0)
            existing["tool_call_count"] = existing.get("tool_call_count", 0) + phase_tool_calls

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

            await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def on_workflow_failed(self, event_data: dict) -> None:
        """Handle WorkflowFailed event.

        Marks execution as failed with error information.
        """
        execution_id = event_data.get("execution_id")
        if not execution_id:
            return

        classification = FailureClassification.from_stored(event_data.get("failure_classification"))
        # Beside the classification at every hop, because the two answer to
        # different evidence and a row that fused them would let a run's own
        # word be summed as a measurement (#1392).
        reported = ReportedFailureReason.from_stored(event_data.get("reported_failure_reason"))
        reported_value = None if reported is None else reported.value

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
                tool_call_count=0,
                error_message=event_data.get("error_message"),
                failure_classification=classification,
                reported_failure_reason=reported,
            ).to_dict()
        else:
            existing["status"] = "failed"
            existing["completed_at"] = event_data.get("failed_at")
            existing["error_message"] = event_data.get("error_message")
            # Beside status, and written on the same line of reasoning: a list
            # filtered or tallied on `failed` alone counts a correct refusal as
            # a defect (#1357). `from_stored` is what makes a pre-#1357 event
            # replay as `unclassified` rather than raising here.
            existing["failure_classification"] = classification.value
            existing["reported_failure_reason"] = reported_value
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

    async def on_execution_tags_added(self, event_data: ExecutionTagsAddedEvent) -> None:
        """Handle ExecutionTagsAdded (#967). Edits current tags, never inherited."""
        event = ExecutionTagsAddedEvent.model_validate(event_data)
        await self._edit_tags(event.execution_id, event.tags, added=True)

    async def on_execution_tags_removed(self, event_data: ExecutionTagsRemovedEvent) -> None:
        """Handle ExecutionTagsRemoved (#967). Edits current tags, never inherited."""
        event = ExecutionTagsRemovedEvent.model_validate(event_data)
        await self._edit_tags(event.execution_id, event.tags, added=False)

    async def on_execution_attached_to_eval(self, event_data: ExecutionAttachedToEvalEvent) -> None:
        """Handle ExecutionAttachedToEval (#967): the run is now an attached member."""
        event = ExecutionAttachedToEvalEvent.model_validate(event_data)
        await self._set_membership(event.execution_id, event.eval_id, AssociationKind.ATTACHED)

    async def on_execution_detached_from_eval(
        self, event_data: ExecutionDetachedFromEvalEvent
    ) -> None:
        """Handle ExecutionDetachedFromEval (#967): the run is in no Eval."""
        event = ExecutionDetachedFromEvalEvent.model_validate(event_data)
        await self._set_membership(event.execution_id, None, None)

    async def _set_membership(
        self, execution_id: str, eval_id: str | None, kind: AssociationKind | None
    ) -> None:
        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if existing:
            existing["eval_id"] = eval_id
            existing["association_kind"] = None if kind is None else kind.value
            await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def _edit_tags(self, execution_id: str, tags: list[str], *, added: bool) -> None:
        if not execution_id:
            return

        existing = await self._store.get(self.PROJECTION_NAME, execution_id)
        if existing:
            existing["tags"] = replay_tag_edit(existing.get("tags") or [], tags, added=added)
            await self._store.save(self.PROJECTION_NAME, execution_id, existing)

    async def get_by_workflow_id(self, workflow_id: str) -> list[WorkflowExecutionSummary]:
        """Get all executions for a workflow.

        Args:
            workflow_id: The workflow template ID.

        Returns:
            List of execution summaries for this workflow.
        """
        # Filtered in the store, not here. Reading every execution and keeping
        # one workflow's decoded the whole history on each call, and
        # /metrics?workflow_id= makes two: the E1 latency gate's p95 was
        # 309-422ms on CI against a 300ms budget for exactly that reason.
        rows = await self._store.query(self.PROJECTION_NAME, filters={"workflow_id": workflow_id})
        executions = [WorkflowExecutionSummary.from_dict(data) for data in rows]

        # Sort by started_at descending (most recent first)
        executions.sort(key=lambda e: e.started_at or "", reverse=True)
        return executions

    async def applied_starts(self, execution_ids: Sequence[str]) -> set[str]:
        """Which of ``execution_ids`` this read model applied the start of, in one query.

        A row alone does not prove it: the #598 fallback in `on_workflow_failed`
        creates a row for a failure whose start was never seen, with no
        `started_at`. That is the shape a dropped start leaves behind (#1545),
        so a start counts as applied only when `started_at` is set. The document
        key is the execution id, so this is a primary-key read, not a JSON filter.
        """
        documents = await read_by_keys(self._store, self.PROJECTION_NAME, execution_ids)
        return {
            key for key, document in documents.items() if document.get("started_at") is not None
        }

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
