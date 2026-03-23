"""Command classes for WorkflowExecution aggregate.

Extracted from WorkflowExecutionAggregate to keep module under LOC threshold.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        PhaseDefinition,
    )


class StartExecutionCommand:
    """Command to start a workflow execution."""

    def __init__(
        self,
        execution_id: str,
        workflow_id: str,
        workflow_name: str,
        total_phases: int,
        inputs: dict[str, Any],
        expected_completion_at: datetime | None = None,
        phase_definitions: list[PhaseDefinition] | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name
        self.total_phases = total_phases
        self.inputs = inputs
        self.expected_completion_at = expected_completion_at
        self.phase_definitions = phase_definitions


class CompleteExecutionCommand:
    """Command to mark a workflow execution as completed."""

    def __init__(
        self,
        execution_id: str,
        completed_phases: int,
        total_phases: int,
        total_input_tokens: int,
        total_output_tokens: int,
        total_cost_usd: Decimal,
        duration_seconds: float,
        artifact_ids: list[str],
    ) -> None:
        self.aggregate_id = execution_id
        self.completed_phases = completed_phases
        self.total_phases = total_phases
        self.total_input_tokens = total_input_tokens
        self.total_output_tokens = total_output_tokens
        self.total_cost_usd = total_cost_usd
        self.duration_seconds = duration_seconds
        self.artifact_ids = artifact_ids


class FailExecutionCommand:
    """Command to mark a workflow execution as failed."""

    def __init__(
        self,
        execution_id: str,
        error: str,
        error_type: str | None,
        failed_phase_id: str | None,
        completed_phases: int,
        total_phases: int,
    ) -> None:
        self.aggregate_id = execution_id
        self.error = error
        self.error_type = error_type
        self.failed_phase_id = failed_phase_id
        self.completed_phases = completed_phases
        self.total_phases = total_phases


class StartPhaseCommand:
    """Command to start a phase execution."""

    def __init__(
        self,
        execution_id: str,
        workflow_id: str,
        phase_id: str,
        phase_name: str,
        phase_order: int,
        session_id: str | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.phase_id = phase_id
        self.phase_name = phase_name
        self.phase_order = phase_order
        self.session_id = session_id


class CompletePhaseCommand:
    """Command to mark a phase as completed with metrics."""

    def __init__(
        self,
        execution_id: str,
        workflow_id: str,
        phase_id: str,
        session_id: str | None,
        artifact_id: str | None,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost_usd: Decimal,
        duration_seconds: float,
    ) -> None:
        self.aggregate_id = execution_id
        self.workflow_id = workflow_id
        self.phase_id = phase_id
        self.session_id = session_id
        self.artifact_id = artifact_id
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.cost_usd = cost_usd
        self.duration_seconds = duration_seconds


class PauseExecutionCommand:
    """Command to pause a workflow execution."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        reason: str | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.reason = reason


class ResumeExecutionCommand:
    """Command to resume a paused workflow execution."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id


class CancelExecutionCommand:
    """Command to cancel a workflow execution."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        reason: str | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.reason = reason


class InterruptExecutionCommand:
    """Command to forcefully interrupt a workflow execution mid-stream."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        git_sha: str | None = None,
        partial_artifact_ids: list[str] | None = None,
        reason: str | None = None,
        partial_input_tokens: int = 0,
        partial_output_tokens: int = 0,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.git_sha = git_sha
        self.partial_artifact_ids = partial_artifact_ids or []
        self.reason = reason
        self.partial_input_tokens = partial_input_tokens
        self.partial_output_tokens = partial_output_tokens


class ProvisionWorkspaceCompletedCommand:
    """Command reported by WorkspaceProvisionHandler after workspace is ready."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        workspace_id: str,
        session_id: str = "",
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.workspace_id = workspace_id
        self.session_id = session_id


class AgentExecutionCompletedCommand:
    """Command reported by AgentExecutionHandler after agent finishes."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        session_id: str | None,
        exit_code: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.session_id = session_id
        self.exit_code = exit_code
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class ArtifactsCollectedCommand:
    """Command reported by ArtifactCollectionHandler after outputs stored."""

    def __init__(
        self,
        execution_id: str,
        phase_id: str,
        artifact_ids: list[str],
        first_content_preview: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.aggregate_id = execution_id
        self.phase_id = phase_id
        self.artifact_ids = artifact_ids
        self.first_content_preview = first_content_preview
        self.session_id = session_id
