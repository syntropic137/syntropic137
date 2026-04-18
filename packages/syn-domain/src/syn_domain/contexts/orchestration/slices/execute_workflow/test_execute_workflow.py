"""Tests for workflow execution value objects and result types.

Engine-specific tests were removed in ISS-196 M6 (WorkflowExecutionEngine deleted).
Processor tests are in test_workflow_execution_processor.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ExecutionMetrics,
    PhaseResult,
    PhaseStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    WorkflowInterruptedError,
    WorkflowNotFoundError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionResult,
)

# =============================================================================
# VALUE OBJECTS TESTS
# =============================================================================


@pytest.mark.integration
class TestExecutionValueObjects:
    """Tests for execution value objects."""

    def test_phase_result_creation(self) -> None:
        """Test PhaseResult immutability."""
        result = PhaseResult(
            phase_id="phase-1",
            status=PhaseStatus.COMPLETED,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            artifact_id="artifact-123",
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
        )

        assert result.phase_id == "phase-1"
        assert result.status == PhaseStatus.COMPLETED
        assert result.total_tokens == 300

    def test_execution_metrics_from_results(self) -> None:
        """Test ExecutionMetrics aggregation."""
        now = datetime.now(UTC)
        results = [
            PhaseResult(
                phase_id="phase-1",
                status=PhaseStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                input_tokens=100,
                output_tokens=200,
                total_tokens=300,
            ),
            PhaseResult(
                phase_id="phase-2",
                status=PhaseStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                input_tokens=150,
                output_tokens=250,
                total_tokens=400,
            ),
        ]

        metrics = ExecutionMetrics.from_results(results)

        assert metrics.total_phases == 2
        assert metrics.completed_phases == 2
        assert metrics.failed_phases == 0
        assert metrics.total_input_tokens == 250
        assert metrics.total_output_tokens == 450
        assert metrics.total_tokens == 700
        # Cost is Lane 2 (#695) — see execution_cost projection

    def test_execution_metrics_with_failed_phase(self) -> None:
        """Test metrics include failed phase counts."""
        results = [
            PhaseResult(
                phase_id="phase-1",
                status=PhaseStatus.COMPLETED,
                input_tokens=100,
                output_tokens=200,
                total_tokens=300,
            ),
            PhaseResult(
                phase_id="phase-2",
                status=PhaseStatus.FAILED,
                error_message="Test failure",
            ),
        ]

        metrics = ExecutionMetrics.from_results(results)

        assert metrics.total_phases == 2
        assert metrics.completed_phases == 1
        assert metrics.failed_phases == 1

    def test_executable_phase_default_config(self) -> None:
        """Test ExecutablePhase has default agent configuration."""
        phase = ExecutablePhase(
            phase_id="phase-1",
            name="Test Phase",
            order=1,
        )

        assert phase.agent_config.provider == "claude"  # Default is now Claude, not mock
        assert phase.agent_config.max_tokens == 4096
        assert phase.output_artifact_type == "text"


# =============================================================================
# WORKFLOW EXECUTION RESULT TESTS
# =============================================================================


class TestWorkflowExecutionResult:
    """Tests for WorkflowExecutionResult."""

    def test_result_creation(self) -> None:
        """Test result creation with basic fields."""
        result = WorkflowExecutionResult(
            workflow_id="wf-123",
            execution_id="exec-123",
            status="completed",
            started_at=datetime.now(UTC),
        )
        assert result.workflow_id == "wf-123"
        assert result.execution_id == "exec-123"
        assert result.status == "completed"

    def test_result_with_error(self) -> None:
        """Test result with error message."""
        result = WorkflowExecutionResult(
            workflow_id="wf-123",
            execution_id="exec-123",
            status="failed",
            started_at=datetime.now(UTC),
            error_message="Phase failed",
        )
        assert result.status == "failed"
        assert result.error_message == "Phase failed"


# =============================================================================
# ERROR TYPES TESTS
# =============================================================================


class TestWorkflowNotFoundError:
    """Tests for WorkflowNotFoundError."""

    def test_carries_workflow_id(self) -> None:
        err = WorkflowNotFoundError("wf-123")
        assert err.workflow_id == "wf-123"
        assert "wf-123" in str(err)


class TestWorkflowInterruptedError:
    """Tests for WorkflowInterruptedError."""

    def test_carries_phase_id_and_reason(self) -> None:
        err = WorkflowInterruptedError(
            phase_id="p-1",
            reason="User stopped",
            git_sha="abc123",
            partial_artifact_ids=["art-1"],
            partial_input_tokens=100,
            partial_output_tokens=50,
        )
        assert err.phase_id == "p-1"
        assert err.reason == "User stopped"
        assert err.git_sha == "abc123"
        assert err.partial_artifact_ids == ["art-1"]

    def test_defaults_are_sensible(self) -> None:
        err = WorkflowInterruptedError(phase_id="p-1")
        assert err.reason is None
        assert err.git_sha is None
        assert err.partial_artifact_ids == []
        assert err.partial_input_tokens == 0
        assert err.partial_output_tokens == 0
