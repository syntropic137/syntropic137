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
    ExecutionMetrics,
    ExecutionStatus,
    PhaseDefinition,
    PhaseResult,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    CancelExecutionCommand,
    CompleteExecutionCommand,
    FailExecutionCommand,
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
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegate_import import (
    capture_and_import_phase,
    close_phase_workspaces,
    remember_leader_native_id,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    completed_phase,
    failed_execution_result,
    failed_phase_outcome,
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
    where_the_work_went,
)
from syn_shared.agents import runner_for_provider

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.control import ExecutionController
    from syn_adapters.conversations import ConversationStoragePort
    from syn_adapters.workspace_backends.agentic.session_capture_service import (
        SessionCapturePort,
    )
    from syn_adapters.workspace_backends.service import WorkspaceService
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
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
    from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
        TokenAccumulator,
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
        self._execution_repo = execution_repository
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
        self._agent_handler = agent_handler  # None → create fresh AgentExecutionHandler per call
        # WHY (issue #726, PR2): the materializer is the optional collaborator
        # that turns ResolvedClaudePlugin entries on the phase into workspace
        # files. Wired through to ``WorkspaceProvisionHandler`` per call.
        self._claude_plugin_materializer = claude_plugin_materializer
        # WHY (#772): mirrors claude_plugin_materializer above but for skills; handler hard-fails (no silent skip) on unmatched skills
        self._skill_materializer = skill_materializer
        # None means capture is OFF, not broken: a deployment with no store
        # configured must behave identically to one from before this existed.
        self._session_capture = session_capture
        # Where a delegate's transcript is read back from. Optional because a
        # deployment without a session store simply imports no delegates; it
        # must never be a reason a phase fails.
        self._session_store = session_store
        self._import_ledger = import_ledger
        # Infrastructure state (not domain state — ephemeral)
        self._active_workspaces: dict[str, ManagedWorkspace] = {}
        self._active_workspace_cms: dict[str, AbstractAsyncContextManager[ManagedWorkspace]] = {}
        self._active_envs: dict[str, dict[str, str]] = {}
        self._active_cmds: dict[str, list[str]] = {}
        self._session_managers: dict[str, SessionLifecycleManager] = {}
        # Per-phase so _finalize_phase can attribute the capture.
        self._phase_session_ids: dict[str, str] = {}
        #: The id each phase's own harness announced on its stream, which is
        #: what the delegate import subtracts from the sweep.
        #:
        #: Keyed by (execution_id, phase_id), NOT phase_id alone. This
        #: processor is shared across concurrent dispatches - see
        #: _DispatchContext above - so two runs of the same workflow share a
        #: phase id. A phase-only key lets one run read the OTHER run's leader,
        #: and a leader id absent from this run's sweep takes the refusal path:
        #: no delegate imported, only a log line. Popped on success so a
        #: completed phase leaves nothing behind.
        self._phase_leader_native_ids: dict[tuple[str, str], str] = {}
        self._phase_tokens: dict[str, TokenAccumulator] = {}
        self._phase_auth_tokens: dict[
            str, tuple[int, int, int, int]
        ] = {}  # (input, output, cache_creation, cache_read)
        self._phase_artifact_ids: dict[str, list[str]] = {}
        self._phase_said: dict[str, str] = {}  # last agent message, for #1195 recovery
        self._phase_started_at: dict[str, datetime] = {}

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
        await self._save_new_and_sync(aggregate)

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
        reason = cancel_reason or "Cancelled by user"
        for _pid, mgr in list(self._session_managers.items()):
            await mgr.complete_cancelled(reason=reason)
        await self._close_phase_workspace_cms(context="cancel")
        return WorkflowExecutionResult(
            workflow_id=workflow_id,
            execution_id=execution_id,
            status="cancelled",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            phase_results=phase_results,
            artifact_ids=all_artifact_ids,
            metrics=ExecutionMetrics.from_results(phase_results),
            error_message=reason,
        )

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
        metrics = ExecutionMetrics.from_results(phase_results)
        complete_cmd = CompleteExecutionCommand(
            execution_id=execution_id,
            completed_phases=metrics.completed_phases,
            total_phases=len(phases),
            total_input_tokens=metrics.total_input_tokens,
            total_output_tokens=metrics.total_output_tokens,
            total_cache_creation_tokens=metrics.total_cache_creation_tokens,
            total_cache_read_tokens=metrics.total_cache_read_tokens,
            duration_seconds=metrics.total_duration_seconds,
            artifact_ids=all_artifact_ids,
        )
        aggregate.complete_execution(complete_cmd)
        await self._save_and_sync(aggregate)
        return WorkflowExecutionResult(
            workflow_id=workflow_id,
            execution_id=execution_id,
            status="completed",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            phase_results=phase_results,
            artifact_ids=all_artifact_ids,
            metrics=metrics,
        )

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
        # BEFORE any await: teardown clears the session-id map, so reading it
        # afterwards timed the phase to the end of cleanup and lost the
        # session_id entirely (#1036). Snapshotted rather than merely read early
        # because the workspace inspection below is an await, and this processor
        # is shared across concurrent dispatches whose teardown clears the same
        # maps.
        started_at_by_phase = dict(self._phase_started_at)
        session_id_by_phase = dict(self._phase_session_ids)
        workspaces = dict(self._active_workspaces)

        # The one window in which "where did this phase's work go" can still be
        # answered: the workspace is alive until _close_phase_workspace_cms
        # below, and after that the branch it pushed is undiscoverable from
        # here (#1200). Never raises, so it cannot displace `error`.
        stranded = await where_the_work_went(workspaces, failed_phase_id)

        failure = failed_phase_outcome(
            error,
            failed_phase_id,
            started_at_by_phase,
            session_id_by_phase,
            stranded=stranded,
        )
        if failure.result is not None:
            phase_results.append(failure.result)

        for _pid, mgr in list(self._session_managers.items()):
            await mgr.complete_failure(error_message=failure.reason)
        await self._close_phase_workspace_cms(context="failure")

        fail_cmd = FailExecutionCommand(
            execution_id=execution_id,
            error=failure.reason,
            error_type=failure.error_type,
            failed_phase_id=failed_phase_id,
            completed_phases=len(completed_phase_ids),
            total_phases=len(phases),
            failed_phase_duration_seconds=failure.duration_seconds,
            pushed_work=failure.pushed_work,
        )
        try:
            aggregate.fail_execution(fail_cmd)
            await self._save_and_sync(aggregate)
        except Exception as save_err:
            logger.error("Failed to save failure event: %s", save_err)
        return failed_execution_result(
            workflow_id=workflow_id,
            execution_id=execution_id,
            started_at=started_at,
            phase_results=phase_results,
            artifact_ids=all_artifact_ids,
            error_message=failure.reason,
        )

    async def _close_phase_workspace_cms(self, context: str) -> None:
        """Close per-phase workspace context managers and clear per-phase state."""
        await close_phase_workspaces(
            context,
            workspace_cms=self._active_workspace_cms,
            workspaces=self._active_workspaces,
            session_ids=self._phase_session_ids,
            leader_native_ids=self._phase_leader_native_ids,
            capture_port=self._session_capture,
            session_store=self._session_store,
            writer=self._observability_writer,
            ledger=self._import_ledger,
        )
        # Both terminal paths (cancel, failure) cleared exactly this set after
        # closing workspaces; they differ only in how they complete sessions.
        self._session_managers.clear()
        self._active_workspaces.clear()
        self._active_envs.clear()
        self._active_cmds.clear()

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
        self._session_managers[todo.phase_id] = session_mgr
        self._phase_started_at[todo.phase_id] = datetime.now(UTC)

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
        self._active_workspaces[todo.phase_id] = result.workspace
        self._active_workspace_cms[todo.phase_id] = result.workspace_cm
        self._active_envs[todo.phase_id] = result.agent_env
        self._active_cmds[todo.phase_id] = result.claude_cmd
        aggregate.provision_workspace_completed(result.command)
        await self._save_and_sync(aggregate)

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
        workspace = self._active_workspaces[todo.phase_id]
        agent_env = self._active_envs[todo.phase_id]
        claude_cmd = self._active_cmds[todo.phase_id]
        session_id = todo.session_id or ""
        self._phase_session_ids[todo.phase_id] = session_id
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
            workspace_id=getattr(workspace, "workspace_id", None),
            agent_model=phase.agent_config.model,
        )
        result = await self._get_agent_handler().handle(
            todo=todo,
            workspace=workspace,
            agent_env=agent_env,
            claude_cmd=claude_cmd,
            session_id=session_id,
            agent_model=phase.agent_config.model,
            timeout_seconds=timeout,
            collector=collector,
            runner=runner,
            on_launch=observer_for(self._session_managers.get(todo.phase_id)),
        )

        remember_leader_native_id(
            self._phase_leader_native_ids,
            (todo.execution_id, todo.phase_id),
            result.stream_result,
        )

        await record_phase_conversation(
            self._conversation_storage,
            result,
            session_id=session_id,
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workflow_id=workflow_id,
            model=phase.agent_config.model,
            started_at=self._phase_started_at.get(todo.phase_id, datetime.now(UTC)),
        )
        self._phase_tokens[todo.phase_id] = result.tokens
        self._phase_said[todo.phase_id] = result.stream_result.last_agent_message or ""
        # Store authoritative totals from CLI result event (includes cache tokens)
        self._phase_auth_tokens[todo.phase_id] = (
            result.command.input_tokens,
            result.command.output_tokens,
            result.command.cache_creation_tokens,
            result.command.cache_read_tokens,
        )

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
        await self._save_and_sync(aggregate)

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
        await self._save_and_sync(aggregate)

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
        workspace = self._active_workspaces.get(todo.phase_id)
        if workspace is None:
            # Defense in depth: in-process this branch is unreachable
            # (_finalize_phase pops _active_workspaces only after
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
            last_agent_message=self._phase_said.pop(todo.phase_id, None),
        )
        all_artifact_ids.extend(result.artifact_ids)
        self._phase_artifact_ids[todo.phase_id] = result.artifact_ids
        phase_outputs.record(todo.phase_id, result.first_content, result.files)
        aggregate.artifacts_collected(result.command)
        await self._save_and_sync(aggregate)

    async def _handle_complete_phase(
        self,
        todo: TodoItem,
        aggregate: WorkflowExecutionAggregate,
        phase_results: list[PhaseResult],
        completed_phase_ids: list[str],
    ) -> None:
        """Dispatch COMPLETE_PHASE."""
        assert todo.phase_id is not None
        # FIRST, and on the real path rather than inside a try: nothing has
        # been popped, the workspace is still alive and the aggregate has not
        # been told this phase succeeded, so the raise IS the outcome (#1184).
        await refuse_to_complete_unsaved_phase(self._active_workspaces, todo)

        self._phase_tokens.pop(todo.phase_id, None)
        auth_tokens = self._phase_auth_tokens.pop(todo.phase_id, None)
        artifact_ids = self._phase_artifact_ids.pop(todo.phase_id, [])
        started_at = self._phase_started_at.pop(todo.phase_id, datetime.now(UTC))

        outcome = completed_phase(
            execution_id=todo.execution_id,
            workflow_id=aggregate.workflow_id or "",
            phase_id=todo.phase_id,
            session_id=todo.session_id,
            started_at=started_at,
            artifact_ids=artifact_ids,
            auth_tokens=auth_tokens,
        )
        phase_results.append(outcome.result)
        completed_phase_ids.append(todo.phase_id)

        aggregate.complete_phase(outcome.command)
        await self._save_and_sync(aggregate)

        await self._finalize_phase(
            todo.phase_id,
            outcome.input_tokens,
            outcome.output_tokens,
            outcome.cache_creation_tokens,
            outcome.cache_read_tokens,
            outcome.total_tokens,
            outcome.duration_seconds,
        )

    async def _finalize_phase(
        self,
        phase_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int,
        cache_read_tokens: int,
        total_tokens: int,
        duration: float,
    ) -> None:
        """Complete session and clean up phase-local state."""
        session_mgr = self._session_managers.pop(phase_id, None)
        if session_mgr is not None:
            await session_mgr.complete_success(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens,
                total_tokens=total_tokens,
                duration_seconds=duration,
                source="processor",
            )

        workspace = self._active_workspaces.pop(phase_id, None)
        session_id = self._phase_session_ids.pop(phase_id, "")
        self._active_envs.pop(phase_id, None)
        self._active_cmds.pop(phase_id, None)
        workspace_cm = self._active_workspace_cms.pop(phase_id, None)

        # BEFORE teardown: once the container is gone so is the spool, and a
        # later probe cannot tell "stored" from "lost forever".
        await capture_and_import_phase(
            self._session_capture,
            workspace,
            session_store=self._session_store,
            writer=self._observability_writer,
            leader_native_ids=self._phase_leader_native_ids,
            session_id=session_id,
            phase_id=phase_id,
            ledger=self._import_ledger,
        )

        if workspace_cm is not None:
            await workspace_cm.__aexit__(None, None, None)

    async def _save_new_and_sync(self, aggregate: WorkflowExecutionAggregate) -> None:
        """Save a NEW aggregate (fails if stream exists) and sync events.

        Uses save_new() with ExpectedVersion.NoStream to prevent duplicate
        execution streams. Raises StreamAlreadyExistsError on conflict.
        """
        uncommitted = list(aggregate._uncommitted_events)
        await self._execution_repo.save_new(aggregate)
        for envelope in uncommitted:
            event = envelope.event
            event_type = getattr(event, "event_type", type(event).__name__)
            event_data = self._serialize_event(event)
            handler_name = self._event_type_to_handler(event_type)
            handler = getattr(self._todo_projection, handler_name, None)
            if handler:
                await handler(event_data)

    async def _save_and_sync(self, aggregate: WorkflowExecutionAggregate) -> None:
        """Save aggregate and sync uncommitted events to local projection."""
        uncommitted = list(aggregate._uncommitted_events)
        await self._execution_repo.save(aggregate)
        for envelope in uncommitted:
            event = envelope.event
            event_type = getattr(event, "event_type", type(event).__name__)
            event_data = self._serialize_event(event)
            handler_name = self._event_type_to_handler(event_type)
            handler = getattr(self._todo_projection, handler_name, None)
            if handler:
                await handler(event_data)

    @staticmethod
    def _serialize_event(event: object) -> dict[str, Any]:
        """Serialize a domain event to a dict for projection handlers."""
        if hasattr(event, "model_dump"):
            return event.model_dump()  # type: ignore[union-attr]
        if hasattr(event, "to_dict"):
            return event.to_dict()  # type: ignore[union-attr]
        return vars(event)

    @staticmethod
    def _event_type_to_handler(event_type: str) -> str:
        """Convert CamelCase event type to on_snake_case handler name."""
        import re

        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", event_type).lower()
        return f"on_{snake}"
