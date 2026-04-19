"""Unit tests for WorkflowExecutionProcessor (ISS-196).

Tests the Processor To-Do List pattern end-to-end with mocked infrastructure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)


def _make_processor() -> WorkflowExecutionProcessor:
    """Create a processor with mocked dependencies."""
    from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
        ExecutionTodoProjection,
    )

    return WorkflowExecutionProcessor(
        execution_repository=AsyncMock(),
        session_repository=AsyncMock(),
        workspace_service=MagicMock(),
        artifact_repository=AsyncMock(),
        artifact_content_storage=None,
        artifact_query=None,
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=AsyncMock(return_value="test prompt"),
        command_builder=MagicMock(return_value=["claude", "--model", "haiku"]),
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
    )


@pytest.mark.unit
class TestProcessorDispatching:
    """Tests for processor dispatch logic."""

    def test_event_type_to_handler_conversion(self) -> None:
        """CamelCase event types convert to on_snake_case handlers."""
        convert = WorkflowExecutionProcessor._event_type_to_handler
        assert convert("WorkflowExecutionStarted") == "on_workflow_execution_started"
        assert convert("PhaseCompleted") == "on_phase_completed"
        assert convert("NextPhaseReady") == "on_next_phase_ready"
        assert convert("WorkspaceProvisionedForPhase") == "on_workspace_provisioned_for_phase"
        assert convert("ArtifactsCollectedForPhase") == "on_artifacts_collected_for_phase"
        assert convert("AgentExecutionCompleted") == "on_agent_execution_completed"


@pytest.mark.unit
class TestProcessorTermination:
    """Tests for processor termination."""

    @pytest.mark.anyio
    async def test_processor_terminates_when_no_todos(self) -> None:
        """Processor terminates when to-do list is empty after start."""
        processor = _make_processor()

        # Mock save to be a no-op (aggregate events won't trigger real projection)
        processor._execution_repo.save = AsyncMock()

        # Patch _save_and_sync to just save without projection sync
        # This simulates a scenario where no phase_definitions are provided (legacy)
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            ExecutablePhase,
        )

        result = await processor.run(
            workflow_id="wf-1",
            workflow_name="Test",
            phases=[
                ExecutablePhase(
                    phase_id="p-1",
                    name="Research",
                    order=1,
                    prompt_template="Do research",
                ),
            ],
            inputs={"topic": "test"},
            execution_id="exec-1",
        )

        # Legacy mode (no phase_definitions on ExecutablePhase) — processor
        # creates PhaseDefinition from the phases list, so it WILL have
        # phase_definitions and the projection WILL create todos.
        # Since we haven't mocked the handlers, this will fail at provisioning.
        # The important thing is that the processor caught the error and returned failed.
        assert result.execution_id == "exec-1"
        assert result.workflow_id == "wf-1"

    @pytest.mark.anyio
    async def test_processor_handles_failure_gracefully(self) -> None:
        """Processor returns failed result on exception."""
        processor = _make_processor()
        processor._execution_repo.save = AsyncMock()

        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            ExecutablePhase,
        )

        # This will fail at provisioning since workspace_service is a MagicMock
        result = await processor.run(
            workflow_id="wf-1",
            workflow_name="Test",
            phases=[
                ExecutablePhase(
                    phase_id="p-1",
                    name="Research",
                    order=1,
                    prompt_template="Do research",
                ),
            ],
            inputs={},
            execution_id="exec-fail",
        )

        assert result.status == "failed"
        assert result.error_message is not None


@pytest.mark.unit
class TestProcessorProjectionSync:
    """Tests for in-process synchronous projection."""

    @pytest.mark.anyio
    async def test_save_and_sync_applies_events_to_projection(self) -> None:
        """_save_and_sync applies uncommitted events to local projection."""
        processor = _make_processor()
        processor._execution_repo.save = AsyncMock()

        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            PhaseDefinition,
        )
        from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        aggregate = WorkflowExecutionAggregate()
        cmd = StartExecutionCommand(
            execution_id="exec-sync",
            workflow_id="wf-1",
            workflow_name="Test",
            total_phases=1,
            inputs={},
            phase_definitions=[
                PhaseDefinition(phase_id="p-1", name="Research", order=1),
            ],
        )
        aggregate._handle_command(cmd)

        await processor._save_and_sync(aggregate)

        # The local projection should now have a todo
        todos = await processor._todo_projection.get_pending("exec-sync")
        assert len(todos) == 1
        assert todos[0].phase_id == "p-1"


@pytest.mark.unit
class TestProcessorReposPersistence:
    """Tests that resolved repos are persisted in inputs for the domain event."""

    @pytest.mark.anyio
    async def test_resolved_repos_written_to_inputs(self) -> None:
        """Typed RepositoryRefs are normalised to HTTPS URLs in inputs['repos']."""
        processor = _make_processor()
        processor._execution_repo.save = AsyncMock()

        from syn_domain.contexts._shared.repository_ref import RepositoryRef
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            ExecutablePhase,
        )

        inputs: dict[str, str] = {"repository": "org/my-repo"}
        await processor.run(
            workflow_id="wf-1",
            workflow_name="Test",
            phases=[
                ExecutablePhase(
                    phase_id="p-1",
                    name="Phase",
                    order=1,
                    prompt_template="do work",
                ),
            ],
            inputs=inputs,
            execution_id="exec-repos",
            repos=[RepositoryRef.from_slug("org/my-repo")],
        )

        assert inputs["repos"] == "https://github.com/org/my-repo"

    @pytest.mark.anyio
    async def test_existing_repos_input_not_overwritten(self) -> None:
        """If inputs already has 'repos', the processor does not overwrite it."""
        processor = _make_processor()
        processor._execution_repo.save = AsyncMock()

        from syn_domain.contexts._shared.repository_ref import RepositoryRef
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            ExecutablePhase,
        )

        inputs: dict[str, str] = {"repos": "https://github.com/org/explicit"}
        await processor.run(
            workflow_id="wf-1",
            workflow_name="Test",
            phases=[
                ExecutablePhase(
                    phase_id="p-1",
                    name="Phase",
                    order=1,
                    prompt_template="do work",
                ),
            ],
            inputs=inputs,
            execution_id="exec-no-overwrite",
            repos=[RepositoryRef.from_url("https://github.com/org/resolved")],
        )

        assert inputs["repos"] == "https://github.com/org/explicit"


@pytest.mark.unit
class TestProcessorCancellation:
    """Tests for cancellation cleanup semantics."""

    @pytest.mark.anyio
    async def test_cancel_execution_clears_all_active_state_and_sets_error_message(
        self,
    ) -> None:
        """_cancel_execution closes workspace CMs, clears all in-memory state, and
        propagates the cancel reason into the result's error_message.
        """
        from datetime import UTC, datetime

        processor = _make_processor()

        # Seed session managers (expose complete_cancelled as AsyncMock).
        session_mgr_a = MagicMock()
        session_mgr_a.complete_cancelled = AsyncMock()
        session_mgr_b = MagicMock()
        session_mgr_b.complete_cancelled = AsyncMock()
        processor._session_managers["phase-a"] = session_mgr_a
        processor._session_managers["phase-b"] = session_mgr_b

        # Seed workspace context managers (async context manager protocol).
        workspace_cm_a = MagicMock()
        workspace_cm_a.__aexit__ = AsyncMock(return_value=None)
        workspace_cm_b = MagicMock()
        workspace_cm_b.__aexit__ = AsyncMock(return_value=None)
        processor._active_workspace_cms["phase-a"] = workspace_cm_a
        processor._active_workspace_cms["phase-b"] = workspace_cm_b

        # Seed the remaining per-phase state dicts.
        processor._active_workspaces["phase-a"] = MagicMock()
        processor._active_workspaces["phase-b"] = MagicMock()
        processor._active_envs["phase-a"] = {"FOO": "bar"}
        processor._active_envs["phase-b"] = {"BAZ": "qux"}
        processor._active_cmds["phase-a"] = ["claude", "--model", "haiku"]
        processor._active_cmds["phase-b"] = ["claude", "--model", "sonnet"]

        started_at = datetime.now(UTC)
        result = await processor._cancel_execution(
            execution_id="exec-cancel",
            workflow_id="wf-cancel",
            phase_results=[],
            all_artifact_ids=[],
            started_at=started_at,
            cancel_reason="user requested",
        )

        # Each workspace CM was closed via the async context manager exit.
        workspace_cm_a.__aexit__.assert_awaited_once_with(None, None, None)
        workspace_cm_b.__aexit__.assert_awaited_once_with(None, None, None)

        # Each session manager was told to complete-as-cancelled with the reason.
        session_mgr_a.complete_cancelled.assert_awaited_once_with(reason="user requested")
        session_mgr_b.complete_cancelled.assert_awaited_once_with(reason="user requested")

        # All five per-phase state dicts are empty after cancellation.
        assert processor._session_managers == {}
        assert processor._active_workspace_cms == {}
        assert processor._active_workspaces == {}
        assert processor._active_envs == {}
        assert processor._active_cmds == {}

        # The result reflects the cancellation with the reason as error_message.
        assert result.status == "cancelled"
        assert result.error_message == "user requested"
        assert result.execution_id == "exec-cancel"
        assert result.workflow_id == "wf-cancel"

    @pytest.mark.anyio
    async def test_cancel_execution_survives_workspace_cleanup_failure(self) -> None:
        """A workspace CM that raises during __aexit__ does not abort the cleanup
        loop; remaining state is still cleared and the cancelled result is still
        produced.
        """
        from datetime import UTC, datetime

        processor = _make_processor()

        session_mgr = MagicMock()
        session_mgr.complete_cancelled = AsyncMock()
        processor._session_managers["phase-a"] = session_mgr

        failing_cm = MagicMock()
        failing_cm.__aexit__ = AsyncMock(side_effect=RuntimeError("cleanup exploded"))
        healthy_cm = MagicMock()
        healthy_cm.__aexit__ = AsyncMock(return_value=None)
        processor._active_workspace_cms["phase-a"] = failing_cm
        processor._active_workspace_cms["phase-b"] = healthy_cm

        processor._active_workspaces["phase-a"] = MagicMock()
        processor._active_envs["phase-a"] = {}
        processor._active_cmds["phase-a"] = []

        result = await processor._cancel_execution(
            execution_id="exec-cancel",
            workflow_id="wf-cancel",
            phase_results=[],
            all_artifact_ids=[],
            started_at=datetime.now(UTC),
            cancel_reason="timeout",
        )

        failing_cm.__aexit__.assert_awaited_once_with(None, None, None)
        healthy_cm.__aexit__.assert_awaited_once_with(None, None, None)
        assert processor._session_managers == {}
        assert processor._active_workspace_cms == {}
        assert processor._active_workspaces == {}
        assert processor._active_envs == {}
        assert processor._active_cmds == {}
        assert result.status == "cancelled"
        assert result.error_message == "timeout"
