"""Unit tests for WorkflowExecutionProcessor (ISS-196).

Tests the Processor To-Do List pattern end-to-end with mocked infrastructure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)
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
class TestAgentRunnerSelection:
    """Provider selects the parser runner."""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("provider", "expected_runner"),
        [
            ("claude", "claude"),
            ("codex", "codex"),
        ],
    )
    async def test_provider_is_forwarded_as_typed_runner(
        self,
        provider: str,
        expected_runner: str,
    ) -> None:
        from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
            TodoAction,
            TodoItem,
        )
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            AgentConfiguration,
            ExecutablePhase,
        )

        processor = _make_processor()
        handler = MagicMock()
        handler.handle = AsyncMock(side_effect=RuntimeError("stop after dispatch"))
        processor._agent_handler = handler
        processor._active_workspaces["p-1"] = MagicMock()
        processor._active_envs["p-1"] = {}
        processor._active_cmds["p-1"] = ["agent"]
        phase = ExecutablePhase(
            phase_id="p-1",
            name="Phase 1",
            order=1,
            agent_config=AgentConfiguration(provider=provider),
            prompt_template="do it",
        )

        with pytest.raises(RuntimeError, match="stop after dispatch"):
            await processor._handle_run_agent(
                TodoItem(
                    execution_id="exec-1",
                    action=TodoAction.RUN_AGENT,
                    phase_id="p-1",
                    session_id="sess-1",
                ),
                phase,
                MagicMock(workflow_id="wf-1"),
            )

        assert handler.handle.await_args.kwargs["runner"] == expected_runner

    @pytest.mark.anyio
    async def test_handle_run_agent_does_not_itself_mark_the_session_launched(self) -> None:
        """Dispatching an agent is an intention, not evidence one existed.

        This frame has decided to run an agent and nothing more; everything
        between here and a process - a dead container, a missing binary, a
        refused exec - can still falsify it. So it hands the observer down to
        the stream, which can tell, and reports nothing itself.

        The agent handler fails before touching the observer, standing in for
        every one of those failures. Move the call back up here and this test
        fails, which is the point: at that ordering the session is already
        marked launched and no reader downstream can tell the difference
        (#1047, #1065).
        """
        from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
            TodoAction,
            TodoItem,
        )
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            AgentConfiguration,
            ExecutablePhase,
        )

        processor = _make_processor()
        handler = MagicMock()
        handler.handle = AsyncMock(side_effect=RuntimeError("stop after dispatch"))
        processor._agent_handler = handler
        processor._active_workspaces["p-1"] = MagicMock()
        processor._active_envs["p-1"] = {}
        processor._active_cmds["p-1"] = ["agent"]

        session_mgr = MagicMock()
        session_mgr.mark_launched = AsyncMock()
        processor._session_managers["p-1"] = session_mgr

        phase = ExecutablePhase(
            phase_id="p-1",
            name="Phase 1",
            order=1,
            agent_config=AgentConfiguration(provider="claude"),
            prompt_template="do it",
        )

        with pytest.raises(RuntimeError, match="stop after dispatch"):
            await processor._handle_run_agent(
                TodoItem(
                    execution_id="exec-1",
                    action=TodoAction.RUN_AGENT,
                    phase_id="p-1",
                    session_id="sess-1",
                ),
                phase,
                MagicMock(workflow_id="wf-1"),
            )

        session_mgr.mark_launched.assert_not_awaited()
        # Handed down rather than called: the fact is still recordable, just
        # not from here.
        assert handler.handle.await_args.kwargs["on_launch"] is session_mgr.mark_launched

    @pytest.mark.anyio
    async def test_handle_run_agent_tolerates_missing_session_manager(self) -> None:
        """No session manager registered for the phase (session tracking
        disabled, repo=None) must not block agent dispatch.
        """
        from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
            TodoAction,
            TodoItem,
        )
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            AgentConfiguration,
            ExecutablePhase,
        )

        processor = _make_processor()
        handler = MagicMock()
        handler.handle = AsyncMock(side_effect=RuntimeError("stop after dispatch"))
        processor._agent_handler = handler
        processor._active_workspaces["p-1"] = MagicMock()
        processor._active_envs["p-1"] = {}
        processor._active_cmds["p-1"] = ["agent"]
        # Deliberately no processor._session_managers["p-1"] entry.

        phase = ExecutablePhase(
            phase_id="p-1",
            name="Phase 1",
            order=1,
            agent_config=AgentConfiguration(provider="claude"),
            prompt_template="do it",
        )

        with pytest.raises(RuntimeError, match="stop after dispatch"):
            await processor._handle_run_agent(
                TodoItem(
                    execution_id="exec-1",
                    action=TodoAction.RUN_AGENT,
                    phase_id="p-1",
                    session_id="sess-1",
                ),
                phase,
                MagicMock(workflow_id="wf-1"),
            )


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
        phase_outputs = PhaseOutputCache()

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
        assert phase_outputs.primary == {}
        # #988: a stale todo must not seed the output TREE either.
        assert phase_outputs.files == {}
        assert "p-1" not in processor._phase_artifact_ids


@pytest.mark.unit
class TestPhaseOutputCacheCarriesTheWholeTree:
    """The live handoff path between COLLECT_ARTIFACTS and the next PROVISION.

    A phase outputs a DIRECTORY (#988). The cache is what carries it from the
    phase that wrote it to the workspace of the phase that reads it, so if it
    keeps only the primary string the fix is undone before injection ever runs
    - and every assertion about injection would still pass.
    """

    def test_record_keeps_both_the_primary_and_the_file_tree(self) -> None:
        from syn_domain.contexts.artifacts import PhaseOutputFile

        cache = PhaseOutputCache()
        files = [
            PhaseOutputFile(source_path="artifacts/output/deliverable.md", content="d"),
            PhaseOutputFile(source_path="artifacts/output/review.yaml", content="r"),
        ]
        cache.record("p-1", "d", files)

        assert cache.primary == {"p-1": "d"}
        assert cache.files == {"p-1": files}

    def test_a_phase_that_produced_nothing_is_not_recorded(self) -> None:
        """An empty entry would read as an authoritative empty tree and stop
        the restart path from re-querying the projection for that phase."""
        cache = PhaseOutputCache()
        cache.record("p-1", None, [])

        assert cache.primary == {}
        assert cache.files == {}

    @pytest.mark.anyio
    async def test_collecting_artifacts_records_the_files_it_collected(self) -> None:
        """The call site, not just the method: _handle_collect_artifacts must
        hand the collected files to the cache, not only first_content."""
        from syn_domain.contexts.artifacts import PhaseOutputFile
        from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
            TodoAction,
            TodoItem,
        )
        from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            ExecutablePhase,
        )
        from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.ArtifactCollectionHandler import (
            ArtifactCollectionResult,
        )

        files = [PhaseOutputFile(source_path="artifacts/output/review.yaml", content="r")]
        processor = _make_processor()
        processor._save_and_sync = AsyncMock()
        processor._active_workspaces["p-1"] = MagicMock()

        handler = MagicMock()
        handler.handle = AsyncMock(
            return_value=ArtifactCollectionResult(
                artifact_ids=["a1"],
                first_content="r",
                command=MagicMock(),
                files=files,
            )
        )

        todo = TodoItem(
            execution_id="exec-1",
            action=TodoAction.COLLECT_ARTIFACTS,
            phase_id="p-1",
            session_id="sess-1",
        )
        phase = ExecutablePhase(phase_id="p-1", name="Research", order=1, prompt_template="x")
        cache = PhaseOutputCache()

        with patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow"
            ".WorkflowExecutionProcessor.ArtifactCollectionHandler",
            return_value=handler,
        ):
            await processor._handle_collect_artifacts(todo, phase, MagicMock(), [], cache)

        assert cache.files == {"p-1": files}
        assert cache.primary == {"p-1": "r"}
