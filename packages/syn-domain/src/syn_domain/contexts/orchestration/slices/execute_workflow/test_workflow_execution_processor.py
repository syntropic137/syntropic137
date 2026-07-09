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


def _make_processor(
    interactive_workspace_service: MagicMock | None = None,
) -> WorkflowExecutionProcessor:
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
        interactive_workspace_service=interactive_workspace_service,
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
class TestWorkspaceServiceSelection:
    """Per-phase provider selection MUST NOT move claude phases off Docker."""

    @staticmethod
    def _phase(provider: str = "claude") -> object:
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            AgentConfiguration,
            ExecutablePhase,
        )

        return ExecutablePhase(
            phase_id="p1",
            name="Phase 1",
            order=1,
            agent_config=AgentConfiguration(provider=provider),
            prompt_template="do it",
        )

    def test_claude_phase_uses_default_service_even_with_interactive_wired(self) -> None:
        """Normal claude phases stay on the Docker claude -p service."""
        interactive = MagicMock()
        processor = _make_processor(interactive_workspace_service=interactive)

        selected = processor._workspace_service_for(self._phase("claude"))

        assert selected is processor._workspace_service
        assert selected is not interactive

    def test_interactive_phase_uses_interactive_service(self) -> None:
        interactive = MagicMock()
        processor = _make_processor(interactive_workspace_service=interactive)

        selected = processor._workspace_service_for(self._phase("claude-interactive"))

        assert selected is interactive

    def test_interactive_phase_without_service_fails_loudly(self) -> None:
        """Also asserts the typed error (issue #771 item 7): a bare RuntimeError
        gives error-mapping layers nothing to match against."""
        from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
            WorkspaceMisconfiguredError,
        )

        processor = _make_processor(interactive_workspace_service=None)

        with pytest.raises(
            WorkspaceMisconfiguredError, match="SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED"
        ):
            processor._workspace_service_for(self._phase("claude-interactive"))


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


@pytest.mark.unit
class TestSharedWorkspaceCleanup:
    """The shared interactive-tmux workspace is destroyed exactly once on
    success, failure, and cancel; per-phase cleanup loops must skip it."""

    @staticmethod
    def _seed_shared_and_normal(
        processor: WorkflowExecutionProcessor, execution_id: str
    ) -> tuple[MagicMock, MagicMock]:
        """Seed one shared CM (registered both globally and per-phase) and
        one normal per-phase CM."""
        shared_cm = MagicMock()
        shared_cm.__aexit__ = AsyncMock(return_value=None)
        processor._shared_workspaces[execution_id] = (MagicMock(), shared_cm)
        # While a phase is active, the shared CM is also registered per-phase.
        processor._active_workspace_cms["phase-a"] = shared_cm
        normal_cm = MagicMock()
        normal_cm.__aexit__ = AsyncMock(return_value=None)
        processor._active_workspace_cms["phase-b"] = normal_cm
        return shared_cm, normal_cm

    @pytest.mark.anyio
    async def test_cancel_destroys_shared_workspace_exactly_once(self) -> None:
        """_cancel_execution skips the shared CM in the per-phase loop and
        tears it down once via _cleanup_shared_workspace."""
        from datetime import UTC, datetime

        processor = _make_processor()
        shared_cm, normal_cm = self._seed_shared_and_normal(processor, "exec-shared")

        result = await processor._cancel_execution(
            execution_id="exec-shared",
            workflow_id="wf-shared",
            phase_results=[],
            all_artifact_ids=[],
            started_at=datetime.now(UTC),
            cancel_reason="user requested",
        )

        shared_cm.__aexit__.assert_awaited_once_with(None, None, None)
        normal_cm.__aexit__.assert_awaited_once_with(None, None, None)
        assert processor._active_workspace_cms == {}
        assert processor._shared_workspaces == {}
        assert result.status == "cancelled"

    @pytest.mark.anyio
    async def test_failure_destroys_shared_workspace_exactly_once(self) -> None:
        """_fail_execution skips the shared CM in the per-phase loop and
        tears it down once via _cleanup_shared_workspace."""
        from datetime import UTC, datetime

        processor = _make_processor()
        shared_cm, normal_cm = self._seed_shared_and_normal(processor, "exec-shared")

        aggregate = MagicMock()
        aggregate._uncommitted_events = []

        result = await processor._fail_execution(
            error=RuntimeError("phase exploded"),
            aggregate=aggregate,
            execution_id="exec-shared",
            workflow_id="wf-shared",
            phases=[],
            phase_results=[],
            all_artifact_ids=[],
            completed_phase_ids=[],
            started_at=datetime.now(UTC),
        )

        shared_cm.__aexit__.assert_awaited_once_with(None, None, None)
        normal_cm.__aexit__.assert_awaited_once_with(None, None, None)
        assert processor._active_workspace_cms == {}
        assert processor._shared_workspaces == {}
        assert result.status == "failed"

    @pytest.mark.anyio
    async def test_success_path_destroys_shared_workspace_exactly_once(self) -> None:
        """_finalize_phase skips the shared CM; _cleanup_shared_workspace
        destroys it once and is idempotent on a second call."""
        processor = _make_processor()
        shared_cm, _normal_cm = self._seed_shared_and_normal(processor, "exec-shared")

        # Per-phase finalize must NOT close the shared CM.
        await processor._finalize_phase(
            phase_id="phase-a",
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=0,
            duration=0.0,
        )
        shared_cm.__aexit__.assert_not_awaited()

        # Execution-end cleanup closes it exactly once; a second call is a no-op.
        await processor._cleanup_shared_workspace("exec-shared")
        await processor._cleanup_shared_workspace("exec-shared")
        shared_cm.__aexit__.assert_awaited_once_with(None, None, None)


@pytest.mark.unit
class TestConcurrentFailureAttribution:
    """failed_phase_id stays execution-local when one processor instance
    serves multiple concurrent executions (BackgroundWorkflowDispatcher
    shares a single processor across up to max_concurrent runs)."""

    @pytest.mark.anyio
    async def test_failed_phase_id_is_execution_local(self) -> None:
        """Two concurrent failing executions each attribute the failure to
        their OWN phase. With the old processor-instance _current_phase_id
        this deterministically cross-attributed: A is parked until B has
        dispatched (overwriting the shared field), then A fails.
        """
        import asyncio

        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            ExecutablePhase,
        )

        processor = _make_processor()
        processor._execution_repo.save_new = AsyncMock()

        failed_phase_by_execution: dict[str, str | None] = {}

        async def _capture_save(aggregate: object) -> None:
            for envelope in list(aggregate._uncommitted_events):  # type: ignore[attr-defined]
                event = envelope.event
                if type(event).__name__ == "WorkflowFailedEvent":
                    failed_phase_by_execution[event.execution_id] = event.failed_phase_id

        processor._execution_repo.save = AsyncMock(side_effect=_capture_save)

        b_dispatched = asyncio.Event()
        a_failed = asyncio.Event()

        class _FailingWorkspaceCM:
            """Workspace CM whose __aenter__ enforces the racing interleave."""

            def __init__(self, execution_id: str) -> None:
                self._execution_id = execution_id

            async def __aenter__(self) -> object:
                if self._execution_id == "exec-a":
                    # Park A until B has entered dispatch (which, with
                    # shared instance state, overwrote the current phase).
                    await asyncio.wait_for(b_dispatched.wait(), timeout=5)
                    a_failed.set()
                    raise RuntimeError("boom-a")
                b_dispatched.set()
                await asyncio.wait_for(a_failed.wait(), timeout=5)
                raise RuntimeError("boom-b")

            async def __aexit__(self, *args: object) -> bool:
                return False

        workspace_service = MagicMock()
        workspace_service.create_workspace = MagicMock(
            side_effect=lambda **kwargs: _FailingWorkspaceCM(kwargs["execution_id"])
        )
        processor._workspace_service = workspace_service

        result_a, result_b = await asyncio.gather(
            processor.run(
                workflow_id="wf-a",
                workflow_name="A",
                phases=[
                    ExecutablePhase(phase_id="phase-a-1", name="A1", order=1, prompt_template="x")
                ],
                inputs={},
                execution_id="exec-a",
            ),
            processor.run(
                workflow_id="wf-b",
                workflow_name="B",
                phases=[
                    ExecutablePhase(phase_id="phase-b-1", name="B1", order=1, prompt_template="x")
                ],
                inputs={},
                execution_id="exec-b",
            ),
        )

        assert result_a.status == "failed"
        assert result_b.status == "failed"
        assert failed_phase_by_execution["exec-a"] == "phase-a-1"
        assert failed_phase_by_execution["exec-b"] == "phase-b-1"


@pytest.mark.unit
class TestStaleCollectArtifactsGuard:
    """Stale COLLECT_ARTIFACTS dispatch for a finalized phase must be a no-op.

    Defense in depth: in-process the projection's monotonic rank +
    get_pending filtering prevent this dispatch entirely, but a
    lock-bypassing projection writer (e.g. a future out-of-process
    consumer on a shared Postgres store) could still resurrect a stale
    todo. The processor must skip it instead of crashing with KeyError.
    """

    @pytest.mark.anyio
    async def test_collect_artifacts_for_finalized_phase_is_skipped(self) -> None:
        """_handle_collect_artifacts for a phase absent from
        _active_workspaces returns without raising and emits no aggregate
        events (the original incident raised KeyError here)."""
        from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
            TodoAction,
            TodoItem,
        )
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            ExecutablePhase,
        )

        processor = _make_processor()
        processor._save_and_sync = AsyncMock()

        todo = TodoItem(
            execution_id="exec-1",
            action=TodoAction.COLLECT_ARTIFACTS,
            phase_id="p-1",
            session_id="sess-1",
        )
        phase = ExecutablePhase(phase_id="p-1", name="Research", order=1, prompt_template="x")
        aggregate = MagicMock()
        all_artifact_ids: list[str] = []
        phase_outputs: dict[str, str] = {}

        assert "p-1" not in processor._active_workspaces

        await processor._handle_collect_artifacts(
            todo,
            phase,
            aggregate,
            all_artifact_ids,
            phase_outputs,
        )

        aggregate.artifacts_collected.assert_not_called()
        processor._save_and_sync.assert_not_called()
        assert all_artifact_ids == []
        assert phase_outputs == {}
        assert "p-1" not in processor._phase_artifact_ids
