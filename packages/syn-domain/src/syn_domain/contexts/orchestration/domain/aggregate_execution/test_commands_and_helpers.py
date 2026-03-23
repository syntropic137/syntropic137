"""Tests for extracted command classes and event handler helpers."""

from __future__ import annotations

from decimal import Decimal

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    AgentExecutionCompletedCommand,
    ArtifactsCollectedCommand,
    CompleteExecutionCommand,
    FailExecutionCommand,
    InterruptExecutionCommand,
    ProvisionWorkspaceCompletedCommand,
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    _evt,
    _parse_phase_definitions,
)


class TestEvtHelper:
    """Tests for _evt() event field extraction helper."""

    def test_typed_event_attribute(self) -> None:
        """_evt returns attribute value from typed events."""

        class FakeEvent:
            workflow_id = "wf-1"

        assert _evt(FakeEvent(), "workflow_id") == "wf-1"

    def test_dict_event_fallback(self) -> None:
        """_evt falls back to dict access for GenericDomainEvent."""

        class DictEvent:
            def __iter__(self):  # noqa: ANN204
                return iter({"workflow_id": "wf-dict"}.items())

        assert _evt(DictEvent(), "workflow_id") == "wf-dict"

    def test_missing_field_returns_default(self) -> None:
        """_evt returns default when field is not found."""

        class EmptyEvent:
            def __iter__(self):  # noqa: ANN204
                return iter({}.items())

        assert _evt(EmptyEvent(), "missing", 42) == 42

    def test_pydantic_event_model_dump(self) -> None:
        """_evt uses model_dump() for Pydantic-style events without the attribute."""

        class PydanticEvent:
            def model_dump(self) -> dict:  # noqa: ANN101
                return {"status": "completed"}

        assert _evt(PydanticEvent(), "status") == "completed"


class TestParsePhaseDefinitions:
    """Tests for _parse_phase_definitions helper."""

    def test_empty_list(self) -> None:
        result = _parse_phase_definitions([])
        assert result == []

    def test_single_phase(self) -> None:
        raw = [{"phase_id": "p-1", "name": "Research", "order": 1}]
        result = _parse_phase_definitions(raw)
        assert len(result) == 1
        assert result[0].phase_id == "p-1"
        assert result[0].name == "Research"
        assert result[0].order == 1
        assert result[0].timeout_seconds == 300  # default

    def test_sorted_by_order(self) -> None:
        raw = [
            {"phase_id": "p-2", "name": "Implement", "order": 2},
            {"phase_id": "p-1", "name": "Research", "order": 1},
            {"phase_id": "p-3", "name": "Review", "order": 3},
        ]
        result = _parse_phase_definitions(raw)
        assert [p.phase_id for p in result] == ["p-1", "p-2", "p-3"]

    def test_custom_timeout(self) -> None:
        raw = [{"phase_id": "p-1", "name": "Long", "order": 1, "timeout_seconds": 600}]
        result = _parse_phase_definitions(raw)
        assert result[0].timeout_seconds == 600


class TestCommandsImportable:
    """Verify all command classes are importable from commands module."""

    def test_start_execution(self) -> None:
        cmd = StartExecutionCommand(
            execution_id="e-1", workflow_id="w-1", workflow_name="Test",
            total_phases=1, inputs={},
        )
        assert cmd.aggregate_id == "e-1"

    def test_complete_execution(self) -> None:
        cmd = CompleteExecutionCommand(
            execution_id="e-1", completed_phases=1, total_phases=1,
            total_input_tokens=100, total_output_tokens=50,
            total_cost_usd=Decimal("0.01"), duration_seconds=10.0,
            artifact_ids=["a-1"],
        )
        assert cmd.aggregate_id == "e-1"

    def test_fail_execution(self) -> None:
        cmd = FailExecutionCommand(
            execution_id="e-1", error="boom", error_type="RuntimeError",
            failed_phase_id="p-1", completed_phases=0, total_phases=1,
        )
        assert cmd.error == "boom"

    def test_interrupt_with_partial_state(self) -> None:
        cmd = InterruptExecutionCommand(
            execution_id="e-1", phase_id="p-1",
            git_sha="abc123", partial_artifact_ids=["a-1"],
            partial_input_tokens=50, partial_output_tokens=25,
        )
        assert cmd.git_sha == "abc123"
        assert cmd.partial_artifact_ids == ["a-1"]

    def test_provision_workspace_completed(self) -> None:
        cmd = ProvisionWorkspaceCompletedCommand(
            execution_id="e-1", phase_id="p-1", workspace_id="ws-1",
        )
        assert cmd.workspace_id == "ws-1"

    def test_agent_execution_completed(self) -> None:
        cmd = AgentExecutionCompletedCommand(
            execution_id="e-1", phase_id="p-1", session_id="s-1",
            exit_code=0, input_tokens=100, output_tokens=50,
        )
        assert cmd.exit_code == 0

    def test_artifacts_collected(self) -> None:
        cmd = ArtifactsCollectedCommand(
            execution_id="e-1", phase_id="p-1", artifact_ids=["a-1", "a-2"],
            first_content_preview="hello",
        )
        assert len(cmd.artifact_ids) == 2
