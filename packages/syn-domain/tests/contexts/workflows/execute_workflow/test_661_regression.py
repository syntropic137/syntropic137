"""Regression tests for #661 platform bug fixes.

Covers:
- Item 1: syn control cancel sets status to 'cancelled' not 'failed'
- Item 3: repos field applies {{variable}} substitution
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    CancelExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionCancelledEvent import (
    ExecutionCancelledEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    _detect_exit_code,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _make_running_aggregate(execution_id: str = "exec-1") -> WorkflowExecutionAggregate:
    """Create an aggregate in RUNNING state."""
    agg = WorkflowExecutionAggregate()
    agg._handle_command(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id="wf-1",
            workflow_name="Test Workflow",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id="p-1", name="Phase 1", order=1)],
        )
    )
    agg._handle_command(
        StartPhaseCommand(
            execution_id=execution_id,
            workflow_id="wf-1",
            phase_id="p-1",
            phase_name="Phase 1",
            phase_order=1,
        )
    )
    return agg


def _make_stream_result(interrupt_requested: bool = False, interrupt_reason: str | None = None):
    """Create a minimal StreamResult mock."""
    sr = MagicMock()
    sr.interrupt_requested = interrupt_requested
    sr.interrupt_reason = interrupt_reason
    sr.line_count = 10
    return sr


def _make_workspace(last_stream_exit_code: int | None = None):
    """Create a minimal ManagedWorkspace mock."""
    ws = MagicMock()
    ws.last_stream_exit_code = last_stream_exit_code
    return ws


def _make_tokens(input_tokens: int = 100, output_tokens: int = 200):
    from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
        TokenAccumulator,
    )

    acc = TokenAccumulator()
    acc.record(input_tokens=input_tokens, output_tokens=output_tokens)
    return acc


# ===========================================================================
# Item 1: Cancel sets 'cancelled' not 'failed'
# ===========================================================================


class TestCancelExitCodeDetection:
    """_detect_exit_code must NOT return 1 when interrupt_requested=True.

    Previously it synthesised exit code 1, conflating cancellation with failure.
    The processor now owns the decision; this function returns the actual process code.
    """

    def test_interrupt_requested_does_not_synthesise_exit_code_1(self):
        """Exit code must reflect workspace state, not the interrupt flag."""
        stream = _make_stream_result(interrupt_requested=True)
        workspace = _make_workspace(last_stream_exit_code=None)
        tokens = _make_tokens()

        exit_code = _detect_exit_code(stream, workspace, "p-1", tokens)

        # Must NOT be 1 (the old synthetic value)
        assert exit_code == 0, (
            "_detect_exit_code must not return 1 for interrupt_requested=True; "
            "the caller handles cancellation routing"
        )

    def test_interrupt_with_nonzero_workspace_exit_returns_workspace_code(self):
        """If process actually exited non-zero (e.g. 130 from SIGINT), return that."""
        stream = _make_stream_result(interrupt_requested=True)
        workspace = _make_workspace(last_stream_exit_code=130)
        tokens = _make_tokens()

        exit_code = _detect_exit_code(stream, workspace, "p-1", tokens)

        assert exit_code == 130

    def test_genuine_failure_returns_nonzero(self):
        """Non-cancel failures with non-zero exit still return that code."""
        stream = _make_stream_result(interrupt_requested=False)
        workspace = _make_workspace(last_stream_exit_code=1)
        tokens = _make_tokens()

        exit_code = _detect_exit_code(stream, workspace, "p-1", tokens)

        assert exit_code == 1

    def test_clean_exit_returns_zero(self):
        """Normal completion returns 0."""
        stream = _make_stream_result(interrupt_requested=False)
        workspace = _make_workspace(last_stream_exit_code=0)
        tokens = _make_tokens()

        exit_code = _detect_exit_code(stream, workspace, "p-1", tokens)

        assert exit_code == 0


class TestCancelExecutionAggregatePath:
    """CancelExecutionCommand must emit ExecutionCancelledEvent and set status CANCELLED."""

    def test_cancel_running_execution_sets_cancelled_status(self):
        """Aggregate sets status to CANCELLED when CancelExecutionCommand is handled."""
        agg = _make_running_aggregate()
        assert agg._status == ExecutionStatus.RUNNING

        agg._handle_command(
            CancelExecutionCommand(
                execution_id="exec-1",
                phase_id="p-1",
                reason="Cancelled by user",
            )
        )

        assert agg._status == ExecutionStatus.CANCELLED

    def test_cancel_emits_execution_cancelled_event(self):
        """CancelExecutionCommand emits ExecutionCancelledEvent, not WorkflowFailedEvent."""
        agg = _make_running_aggregate()
        agg._handle_command(
            CancelExecutionCommand(
                execution_id="exec-1",
                phase_id="p-1",
                reason="Cancelled by user",
            )
        )

        event_types = [type(e.event).__name__ for e in agg._uncommitted_events]
        assert "ExecutionCancelledEvent" in event_types
        assert "WorkflowFailedEvent" not in event_types

    def test_cancel_event_carries_reason(self):
        """Cancellation reason is preserved in the emitted event."""
        agg = _make_running_aggregate()
        agg._handle_command(
            CancelExecutionCommand(
                execution_id="exec-1",
                phase_id="p-1",
                reason="Cancelled by user",
            )
        )

        cancelled_events = [
            e.event for e in agg._uncommitted_events if isinstance(e.event, ExecutionCancelledEvent)
        ]
        assert len(cancelled_events) == 1
        assert cancelled_events[0].reason == "Cancelled by user"


# ===========================================================================
# Item 3: repos field variable substitution
# ===========================================================================


def _make_workflow_with_repos(repos: list[str]) -> MagicMock:
    """Mock WorkflowTemplateAggregate with a repos list."""
    wf = MagicMock()
    wf.repos = repos
    wf._repository_url = None
    wf.input_declarations = []
    return wf


def _empty_cmd(inputs: dict[str, str] | None = None) -> ExecuteWorkflowCommand:
    """Create a minimal ExecuteWorkflowCommand with no typed repos."""
    return ExecuteWorkflowCommand(
        aggregate_id="wf-test",
        inputs=inputs or {},
    )


class TestReposVariableSubstitution:
    """ExecuteWorkflowHandler._resolve_repos must apply {{variable}} substitution."""

    def test_variable_in_repos_resolves_with_input(self):
        """{{owner}}/app + merged_inputs["owner"] = acme -> full GitHub URL."""
        wf = _make_workflow_with_repos(["{{owner}}/app"])
        result = ExecuteWorkflowHandler._resolve_repos(
            _empty_cmd(),
            {"owner": "acme"},
            wf,  # type: ignore[arg-type]
        )

        assert result == ["https://github.com/acme/app"]

    def test_variable_in_full_url_resolves(self):
        """Full URL template resolves correctly."""
        wf = _make_workflow_with_repos(["https://github.com/{{org}}/{{repo}}"])
        result = ExecuteWorkflowHandler._resolve_repos(
            _empty_cmd(),
            {"org": "myorg", "repo": "myapp"},
            wf,  # type: ignore[arg-type]
        )

        assert result == ["https://github.com/myorg/myapp"]

    def test_unresolved_placeholder_raises_value_error(self):
        """Missing input for {{variable}} must raise ValueError, not silently fall back."""
        wf = _make_workflow_with_repos(["{{owner}}/app"])

        with pytest.raises(ValueError, match="Unresolved placeholders"):
            ExecuteWorkflowHandler._resolve_repos(
                _empty_cmd(),
                {},
                wf,  # type: ignore[arg-type]
            )

    def test_unresolved_placeholder_error_names_the_variable(self):
        """Error message must name the unresolved variable to aid debugging."""
        wf = _make_workflow_with_repos(["{{repository}}/app"])

        with pytest.raises(ValueError, match="repository"):
            ExecuteWorkflowHandler._resolve_repos(
                _empty_cmd(),
                {},
                wf,  # type: ignore[arg-type]
            )

    def test_static_url_passes_through_unchanged(self):
        """Static repos without {{}} are returned as-is (no normalisation change)."""
        wf = _make_workflow_with_repos(["https://github.com/acme/app"])
        result = ExecuteWorkflowHandler._resolve_repos(
            _empty_cmd(),
            {},
            wf,  # type: ignore[arg-type]
        )

        assert result == ["https://github.com/acme/app"]

    def test_multiple_repos_all_resolved(self):
        """All repos in the list get substitution applied."""
        wf = _make_workflow_with_repos(["{{owner}}/app1", "{{owner}}/app2"])
        result = ExecuteWorkflowHandler._resolve_repos(
            _empty_cmd(),
            {"owner": "acme"},
            wf,  # type: ignore[arg-type]
        )

        assert result == [
            "https://github.com/acme/app1",
            "https://github.com/acme/app2",
        ]

    def test_runtime_input_takes_precedence_over_workflow_repos(self):
        """If merged_inputs contains 'repos' CSV, workflow.repos is ignored entirely."""
        wf = _make_workflow_with_repos(["https://github.com/stored/repo"])
        result = ExecuteWorkflowHandler._resolve_repos(
            _empty_cmd(),
            {"repos": "https://github.com/runtime/repo"},
            wf,
        )

        assert result == ["https://github.com/runtime/repo"]

    def test_empty_repos_falls_through_to_repository_url(self):
        """When workflow.repos is empty, falls back to repository_url (existing behaviour)."""
        wf = MagicMock()
        wf.repos = []
        wf._repository_url = "https://github.com/acme/fallback"
        wf.input_declarations = []

        result = ExecuteWorkflowHandler._resolve_repos(
            _empty_cmd(),
            {},
            wf,  # type: ignore[arg-type]
        )

        assert result == ["https://github.com/acme/fallback"]
