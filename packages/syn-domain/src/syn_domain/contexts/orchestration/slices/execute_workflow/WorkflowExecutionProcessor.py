"""WorkflowExecutionProcessor — reads to-do list, dispatches to handlers (ISS-196)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ExecutionStatus,
    PhaseDefinition,
    PhaseResult,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    CancelExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    observer_for,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
    AgentExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.ArtifactCollectionHandler import (
    ArtifactCollectionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    ProvisionResult,
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_conversation import (
    record_phase_conversation,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    cancelled_execution,
    completed_execution,
    completed_phase,
    failed_phase_outcome,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
    PhaseRuntime,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    AgentHandlerProtocol,
    ArtifactRepository,
    CommandBuilder,
    ExecutionRepository,
    PhaseOutputCache,
    PromptBuilder,
    Runner,
    SessionRepository,
    TodoProjection,
    WorkflowExecutionResult,  # re-exported for backward compatibility
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.unpushed_work_guard import (
    refuse_to_complete_unsaved_phase,
)
from syn_shared.agents import runner_for_provider

if TYPE_CHECKING:
    from syn_adapters.control import ExecutionController
    from syn_adapters.conversations import ConversationStoragePort
    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCapturePort,
    )
    from syn_adapters.workspace_backends.service import WorkspaceService
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.agent_sessions.delegate_usage import SessionStorePort
    from syn_domain.contexts.agent_sessions.import_ledger import ImportLedgerPort
    from syn_domain.contexts.artifacts.domain.ports.artifact_storage import (
        ArtifactContentStoragePort,
    )
    from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
        ArtifactQueryServiceProtocol,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
        ClaudePluginMaterializerProtocol,
        SkillMaterializerProtocol,
    )

logger = logging.getLogger(__name__)


@dataclass
class _DispatchContext:
    """Execution-local dispatch state, created per run().

    D3 fix (stress 2026-06-10), hardened for concurrent dispatch: tracks
    the phase currently being dispatched so a workflow-level failure can
    mark the inner phase record as ``failed`` instead of stranding it at
    ``running``. Carried as a per-run object (not processor instance
    state) because BackgroundWorkflowDispatcher shares one processor
    across up to max_concurrent executions; instance state would let a
    concurrent execution overwrite the value and _fail_execution would
    emit a failed_phase_id belonging to a different execution.
    """

    current_phase_id: str | None = None


class WorkflowExecutionProcessor:
    """Reads the to-do list and dispatches to handlers. Zero business logic."""

    def __init__(
        self,
        execution_repository: ExecutionRepository,
        session_repository: SessionRepository,
        workspace_service: WorkspaceService,
        artifact_repository: ArtifactRepository,
        artifact_content_storage: ArtifactContentStoragePort | None,
        artifact_query: ArtifactQueryServiceProtocol | None,
        conversation_storage: ConversationStoragePort | None,
        observability_writer: ObservabilityRecorder | None,
        controller: ExecutionController | None,
        prompt_builder: PromptBuilder,
        command_builder: CommandBuilder,
        todo_projection: TodoProjection | None = None,
        agent_handler: AgentHandlerProtocol | None = None,
        claude_plugin_materializer: ClaudePluginMaterializerProtocol | None = None,
        skill_materializer: SkillMaterializerProtocol | None = None,
        session_capture: SessionCapturePort | None = None,
        session_store: SessionStorePort | None = None,
        import_ledger: ImportLedgerPort | None = None,
    ) -> None:
        self._session_repo = session_repository
        self._workspace_service = workspace_service
        self._artifact_repo = artifact_repository
        self._artifact_content_storage = artifact_content_storage
        self._artifact_query = artifact_query
        self._conversation_storage = conversation_storage
        self._observability_writer = observability_writer
        self._controller = controller
        self._prompt_builder = prompt_builder
        self._command_builder = command_builder
        assert todo_projection is not None, "todo_projection is required"
        self._todo_projection: TodoProjection = todo_projection
        self._journal = ExecutionJournal(execution_repository, todo_projection)
        self._agent_handler = agent_handler  # None → create fresh AgentExecutionHandler per call
        # WHY (issue #726, PR2): the materializer is the optional collaborator
        # that turns ResolvedClaudePlugin entries on the phase into workspace
        # files. Wired through to ``WorkspaceProvisionHandler`` per call.
        self._claude_plugin_materializer = claude_plugin_materializer
        # WHY (#772): mirrors claude_plugin_materializer above but for skills; handler hard-fails (no silent skip) on unmatched skills
        self._skill_materializer = skill_materializer
        # Infrastructure state (not domain state — ephemeral). One object, not
        # thirteen maps: see `phase_runtime` for why they are only ever correct
        # together, and why this processor should not know they are maps at all.
        self._runtime = PhaseRuntime(
            capture_port=session_capture,
            session_store=session_store,
            writer=observability_writer,
            ledger=import_ledger,
        )

    async def run(
        self,
        workflow_id: str,
        workflow_name: str,
        phases: list[ExecutablePhase],
        inputs: dict[str, Any],
        execution_id: str,
        repos: list[RepositoryRef] | None = None,
        expected_completion_at: datetime | None = None,
    ) -> WorkflowExecutionResult:
        """Execute a workflow using the Processor To-Do List pattern."""
        started_at = datetime.now(UTC)
        # PromptBuilder reads ``inputs["repos"]`` for ``{{repos}}`` template substitution.
        # ADR-063: write the canonical HTTPS form of typed RepositoryRef so the prompt
        # never sees un-normalized slugs. TODO(#712): replace this with typed access
        # once PromptBuilder consumes ``RepositoryRef`` directly.
        if repos and "repos" not in inputs:
            inputs["repos"] = ",".join(r.https_url for r in repos)
        self._inputs = inputs
        aggregate = WorkflowExecutionAggregate()

        phase_definitions = [
            PhaseDefinition(
                phase_id=p.phase_id,
                name=p.name,
                order=p.order,
                timeout_seconds=p.timeout_seconds or p.agent_config.timeout_seconds,
            )
            for p in phases
        ]
        phase_map = {p.phase_id: p for p in phases}

        start_cmd = StartExecutionCommand(
            execution_id=execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            total_phases=len(phases),
            inputs=inputs,
            expected_completion_at=expected_completion_at,
            phase_definitions=phase_definitions,
        )
        aggregate.start_execution(start_cmd)
        await self._journal.open(aggregate)

        phase_results: list[PhaseResult] = []
        all_artifact_ids: list[str] = []
        completed_phase_ids: list[str] = []
        phase_outputs = PhaseOutputCache()
        dispatch_ctx = _DispatchContext()

        try:
            await self._drain_todo_list(
                execution_id=execution_id,
                aggregate=aggregate,
                phase_map=phase_map,
                phase_results=phase_results,
                all_artifact_ids=all_artifact_ids,
                completed_phase_ids=completed_phase_ids,
                phase_outputs=phase_outputs,
                repos=repos,
                dispatch_ctx=dispatch_ctx,
            )
            if aggregate.status == ExecutionStatus.CANCELLED:
                return await self._cancel_execution(
                    execution_id,
                    workflow_id,
                    phase_results,
                    all_artifact_ids,
                    started_at,
                    cancel_reason=aggregate.cancel_reason,
                )
            return await self._complete_execution(
                aggregate,
                execution_id,
                workflow_id,
                phases,
                phase_results,
                all_artifact_ids,
                started_at,
            )
        except Exception as e:
            logger.exception(
                "Workflow execution failed (exec=%s, workflow=%s): %s",
                execution_id,
                workflow_id,
                e,
            )
            return await self._fail_execution(
                e,
                aggregate,
                execution_id,
                workflow_id,
                phases,
                phase_results,
                all_artifact_ids,
                completed_phase_ids,
                started_at,
                failed_phase_id=dispatch_ctx.current_phase_id,
            )

    async def _drain_todo_list(
        self,
        execution_id: str,
        aggregate: WorkflowExecutionAggregate,
        phase_map: dict[str, ExecutablePhase],
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        completed_phase_ids: list[str],
        phase_outputs: PhaseOutputCache,
        repos: list[RepositoryRef] | None,
        dispatch_ctx: _DispatchContext,
    ) -> None:
        """Process to-do items until the list is empty (all phases done or cancelled)."""
        while True:
            todos = await self._todo_projection.get_pending(execution_id)
            if not todos:
                break
            await self._dispatch(
                todo=todos[0],
                aggregate=aggregate,
                phase_map=phase_map,
                phase_results=phase_results,
                all_artifact_ids=all_artifact_ids,
                completed_phase_ids=completed_phase_ids,
                phase_outputs=phase_outputs,
                repos=repos,
                dispatch_ctx=dispatch_ctx,
            )

    async def _dispatch(
        self,
        todo: TodoItem,
        aggregate: WorkflowExecutionAggregate,
        phase_map: dict[str, ExecutablePhase],
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        completed_phase_ids: list[str],
        phase_outputs: PhaseOutputCache,
        repos: list[RepositoryRef] | None,
        dispatch_ctx: _DispatchContext,
    ) -> None:
        """Dispatch a single to-do item to its handler."""
        assert todo.phase_id is not None
        phase = phase_map[todo.phase_id]
        # D3 (stress 2026-06-10): record the phase under dispatch so
        # _fail_execution can attribute a workflow-level failure to a
        # real phase id and unstrand the inner phase record. Stored on
        # the per-run _DispatchContext, never on the shared processor.
        dispatch_ctx.current_phase_id = todo.phase_id
        if todo.action == TodoAction.PROVISION_WORKSPACE:
            await self._handle_provision(
                todo,
                phase,
                aggregate,
                repos,
                completed_phase_ids,
                phase_outputs,
            )
        elif todo.action == TodoAction.RUN_AGENT:
            await self._handle_run_agent(todo, phase, aggregate)
        elif todo.action == TodoAction.COLLECT_ARTIFACTS:
            await self._handle_collect_artifacts(
                todo,
                phase,
                aggregate,
                all_artifact_ids,
                phase_outputs,
            )
        elif todo.action == TodoAction.COMPLETE_PHASE:
            await self._handle_complete_phase(todo, aggregate, phase_results, completed_phase_ids)
            # The phase finished cleanly; a later workflow-level failure
            # (between phases) must not be attributed to it.
            dispatch_ctx.current_phase_id = None

    async def _cancel_execution(
        self,
        execution_id: str,
        workflow_id: str,
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        started_at: datetime,
        cancel_reason: str | None = None,
    ) -> WorkflowExecutionResult:
        """Close open sessions as cancelled and return cancelled result.

        Called when the to-do list empties due to ExecutionCancelledEvent.
        The aggregate is already in CANCELLED status - no new command needed.
        """
        cancellation = cancelled_execution(cancel_reason, phase_results, all_artifact_ids)
        await self._runtime.report_cancelled(cancellation.reason)
        await self._runtime.abandon_all("cancel")
        return cancellation.execution_result(workflow_id, execution_id, started_at=started_at)

    async def _complete_execution(
        self,
        aggregate: WorkflowExecutionAggregate,
        execution_id: str,
        workflow_id: str,
        phases: list[ExecutablePhase],
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        started_at: datetime,
    ) -> WorkflowExecutionResult:
        """Build completion command, save, and return success result."""
        completion = completed_execution(phase_results, all_artifact_ids)
        aggregate.complete_execution(completion.as_command(execution_id, total_phases=len(phases)))
        await self._journal.append(aggregate)
        return completion.execution_result(workflow_id, execution_id, started_at=started_at)

    async def _fail_execution(
        self,
        error: Exception,
        aggregate: WorkflowExecutionAggregate,
        execution_id: str,
        workflow_id: str,
        phases: list[ExecutablePhase],
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        completed_phase_ids: list[str],
        started_at: datetime,
        failed_phase_id: str | None = None,
    ) -> WorkflowExecutionResult:
        """Close open sessions, save failure event, and return failed result.

        ``failed_phase_id`` comes from the run's own _DispatchContext so
        it always belongs to THIS execution, even with concurrent runs
        sharing the processor instance.
        """
        # BEFORE any await: teardown clears both maps, so reading them
        # afterwards timed the phase to the end of cleanup and lost the
        # session_id entirely (#1036).
        timings = self._runtime.timings()
        # Before the teardown below, the only window in which it is askable (#1200).
        observed = await self._runtime.observe(failed_phase_id)
        failure = failed_phase_outcome(
            error, failed_phase_id, timings.started_at, timings.session_ids, observed=observed
        )
        if failure.result is not None:
            phase_results.append(failure.result)

        await self._runtime.report_failed(failure.reason)
        await self._runtime.abandon_all("failure")

        fail_cmd = failure.as_command(
            execution_id, completed_phases=len(completed_phase_ids), total_phases=len(phases)
        )
        try:
            aggregate.fail_execution(fail_cmd)
            await self._journal.append(aggregate)
        except Exception as save_err:
            logger.error("Failed to save failure event: %s", save_err)
        return failure.execution_result(
            workflow_id,
            execution_id,
            started_at=started_at,
            phase_results=phase_results,
            artifact_ids=all_artifact_ids,
        )

    async def _handle_provision(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        repos: list[RepositoryRef] | None,
        completed_phase_ids: list[str],
        phase_outputs: PhaseOutputCache,
    ) -> None:
        """Dispatch PROVISION_WORKSPACE."""
        assert todo.phase_id is not None
        session_id = str(uuid4())
        start_cmd = StartPhaseCommand(
            execution_id=todo.execution_id,
            workflow_id=aggregate.workflow_id or "",
            phase_id=todo.phase_id,
            phase_name=phase.name,
            phase_order=phase.order,
            session_id=session_id,
        )
        aggregate.start_phase(start_cmd)

        session_mgr = SessionLifecycleManager(
            repository=self._session_repo,
            session_id=session_id,
            workflow_id=aggregate.workflow_id or "",
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            agent_provider=phase.agent_config.provider,
            agent_model=phase.agent_config.model,
            repos=[r.slug for r in repos] if repos else [],
            observability=self._observability_writer,
        )
        await session_mgr.start()
        self._runtime.begin(
            todo.phase_id, session_manager=session_mgr, started_at=datetime.now(UTC)
        )

        # ADR-063: convert typed RepositoryRef → HTTPS URL at the workspace seam.
        repo_urls = [r.https_url for r in (repos or [])]
        result = await self._provision_workspace(
            todo=todo,
            phase=phase,
            aggregate=aggregate,
            session_id=session_id,
            repo_urls=repo_urls,
            completed_phase_ids=completed_phase_ids,
            phase_outputs=phase_outputs,
        )
        self._runtime.attach_workspace(
            todo.phase_id,
            workspace=result.workspace,
            workspace_cm=result.workspace_cm,
            agent_env=result.agent_env,
            claude_cmd=result.claude_cmd,
        )
        await self._runtime.record_starting_point(todo.phase_id)
        aggregate.provision_workspace_completed(result.command)
        await self._journal.append(aggregate)

    async def _provision_workspace(
        self,
        *,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        session_id: str,
        repo_urls: list[str],
        completed_phase_ids: list[str],
        phase_outputs: PhaseOutputCache,
    ) -> ProvisionResult:
        """Provision this phase's own workspace and build its ProvisionResult."""
        provision_handler = WorkspaceProvisionHandler(
            workspace_service=self._workspace_service,
            prompt_builder=self._prompt_builder,
            command_builder=self._command_builder,
            claude_plugin_materializer=self._claude_plugin_materializer,
            skill_materializer=self._skill_materializer,
        )
        artifacts = ArtifactCollector(
            self._artifact_repo, self._artifact_content_storage, self._artifact_query
        )
        return await provision_handler.handle(
            todo=todo,
            phase=phase,
            workflow_id=aggregate.workflow_id or "",
            session_id=session_id,
            repos=repo_urls,
            artifacts=artifacts,
            completed_phase_ids=completed_phase_ids,
            phase_outputs=phase_outputs,
            inputs=self._inputs,
        )

    def _get_agent_handler(self) -> AgentHandlerProtocol:
        """Return the injected handler, or create a fresh real one (default behaviour)."""
        if self._agent_handler is not None:
            return self._agent_handler
        return AgentExecutionHandler(controller=self._controller)

    async def _handle_run_agent(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
    ) -> None:
        """Dispatch RUN_AGENT."""
        assert todo.phase_id is not None
        session_id = todo.session_id or ""
        launch = self._runtime.launch(todo.phase_id, session_id=session_id)
        workflow_id = aggregate.workflow_id or ""
        timeout = phase.timeout_seconds or phase.agent_config.timeout_seconds
        # Raises on an unknown or removed provider instead of defaulting to
        # the claude parser. The execution boundary
        # (_build_agent_config_from_phase) already rejected it, so reaching
        # that raise means a new entry point skipped the gate.
        runner: Runner = runner_for_provider(phase.agent_config.provider, phase_id=phase.phase_id)

        collector = ObservabilityCollector(
            writer=self._observability_writer,
            session_id=session_id,
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workspace_id=getattr(launch.workspace, "workspace_id", None),
            agent_model=phase.agent_config.model,
        )
        result = await self._get_agent_handler().handle(
            todo=todo,
            workspace=launch.workspace,
            agent_env=launch.agent_env,
            claude_cmd=launch.claude_cmd,
            session_id=session_id,
            agent_model=phase.agent_config.model,
            timeout_seconds=timeout,
            collector=collector,
            runner=runner,
            on_launch=observer_for(launch.session_manager),
        )

        self._runtime.remember_leader(
            todo.phase_id, execution_id=todo.execution_id, stream_result=result.stream_result
        )

        await record_phase_conversation(
            self._conversation_storage,
            result,
            session_id=session_id,
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workflow_id=workflow_id,
            model=phase.agent_config.model,
            started_at=launch.started_at,
        )
        self._runtime.record_agent_run(todo.phase_id, result)

        if result.stream_result.interrupt_requested:
            await self._handle_cancel_signal(todo, result, aggregate)
            return

        if result.command.exit_code != 0:
            reason = result.stream_result.error_reason
            base = (
                f"Agent failed: {reason} (phase={todo.phase_id}, exit_code={result.command.exit_code})"
                if reason
                else f"Agent execution failed for phase {todo.phase_id} (exit_code={result.command.exit_code})"
            )
            msg = f"{base} (tokens={result.tokens.input_tokens}+{result.tokens.output_tokens})"
            logger.error(msg)
            raise RuntimeError(msg)

        aggregate.agent_execution_completed(result.command)
        await self._journal.append(aggregate)

    async def _handle_cancel_signal(
        self,
        todo: TodoItem,
        result: AgentExecutionResult,
        aggregate: WorkflowExecutionAggregate,
    ) -> None:
        """Dispatch CancelExecutionCommand when the agent stream was interrupted by a cancel signal."""
        assert todo.phase_id is not None, "phase_id must be set for a running agent todo"
        cancel_cmd = CancelExecutionCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            reason=result.stream_result.interrupt_reason or "Cancelled by user",
        )
        aggregate.cancel_execution(cancel_cmd)
        await self._journal.append(aggregate)

    async def _handle_collect_artifacts(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        all_artifact_ids: list[str],
        phase_outputs: PhaseOutputCache,
    ) -> None:
        """Dispatch COLLECT_ARTIFACTS."""
        assert todo.phase_id is not None
        workspace = self._runtime.workspace_for(todo.phase_id)
        if workspace is None:
            # Defense in depth: in-process this branch is unreachable
            # (the runtime gives up a phase's workspace only after
            # on_phase_completed locks the phase at rank 99, and
            # get_pending filters stale items), but a lock-bypassing
            # projection writer (e.g. a future out-of-process consumer on
            # a shared Postgres store) could resurrect a stale todo.
            # Skip it instead of crashing the workflow with KeyError.
            logger.warning(
                "Skipping stale COLLECT_ARTIFACTS for finalized phase %s "
                "(execution %s): no active workspace",
                todo.phase_id,
                todo.execution_id,
            )
            return
        artifacts = ArtifactCollector(
            self._artifact_repo, self._artifact_content_storage, self._artifact_query
        )
        collection_handler = ArtifactCollectionHandler(artifact_collector=artifacts)
        result = await collection_handler.handle(
            todo=todo,
            workspace=workspace,
            workflow_id=aggregate.workflow_id or "",
            session_id=todo.session_id or "",
            phase_name=phase.name,
            output_artifact_types=phase.output_artifact_types,
            last_agent_message=self._runtime.take_last_message(todo.phase_id),
        )
        all_artifact_ids.extend(result.artifact_ids)
        self._runtime.record_artifacts(todo.phase_id, result.artifact_ids)
        phase_outputs.record(todo.phase_id, result.first_content, result.files)
        aggregate.artifacts_collected(result.command)
        await self._journal.append(aggregate)

    async def _handle_complete_phase(
        self,
        todo: TodoItem,
        aggregate: WorkflowExecutionAggregate,
        phase_results: list[PhaseResult],
        completed_phase_ids: list[str],
    ) -> None:
        """Dispatch COMPLETE_PHASE.

        THE ORDER OF THE FOUR STEPS BELOW IS THE GUARANTEE (#1184). The guard
        runs before the phase gives anything up, before the aggregate is told
        it succeeded, before that is persisted, and before the runtime tears
        the workspace down. Every one of those is a point of no return, and the
        guard is only a guard on the near side of all four.
        """
        assert todo.phase_id is not None
        # FIRST, and on the real path rather than inside a try: nothing has
        # been popped, the workspace is still alive and the aggregate has not
        # been told this phase succeeded, so the raise IS the outcome (#1184).
        await refuse_to_complete_unsaved_phase(self._runtime.live_workspaces, todo)

        harvest = self._runtime.harvest(todo.phase_id)
        outcome = completed_phase(
            execution_id=todo.execution_id,
            workflow_id=aggregate.workflow_id or "",
            phase_id=todo.phase_id,
            session_id=todo.session_id,
            started_at=harvest.started_at,
            artifact_ids=harvest.artifact_ids,
            auth_tokens=harvest.auth_tokens,
        )
        phase_results.append(outcome.result)
        completed_phase_ids.append(todo.phase_id)

        aggregate.complete_phase(outcome.command)
        await self._journal.append(aggregate)

        await self._runtime.finalize(
            todo.phase_id,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            cache_creation_tokens=outcome.cache_creation_tokens,
            cache_read_tokens=outcome.cache_read_tokens,
            total_tokens=outcome.total_tokens,
            duration_seconds=outcome.duration_seconds,
        )
