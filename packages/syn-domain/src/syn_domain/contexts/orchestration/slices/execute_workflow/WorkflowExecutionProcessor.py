"""WorkflowExecutionProcessor — reads to-do list, dispatches to handlers (ISS-196)."""

from __future__ import annotations

import logging
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
    CompletePhaseCommand,
    FailExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ConversationRecorder import (
    ConversationRecorder,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
    AgentExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.ArtifactCollectionHandler import (
    ArtifactCollectionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.PhaseResultBuilder import (
    PhaseResultBuilder,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    AgentHandlerProtocol,
    ArtifactRepository,
    CommandBuilder,
    ExecutionRepository,
    PromptBuilder,
    SessionRepository,
    TodoProjection,
    WorkflowExecutionResult,  # re-exported for backward compatibility
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from syn_adapters.control import ExecutionController
    from syn_adapters.conversations import ConversationStoragePort
    from syn_adapters.workspace_backends.service import WorkspaceService
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.artifacts.domain.ports.artifact_storage import (
        ArtifactContentStoragePort,
    )
    from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
        ArtifactQueryServiceProtocol,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        ObservabilityRecorder,
    )

logger = logging.getLogger(__name__)


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
        # Infrastructure state (not domain state — ephemeral)
        self._active_workspaces: dict[str, ManagedWorkspace] = {}
        self._active_workspace_cms: dict[str, AbstractAsyncContextManager[ManagedWorkspace]] = {}
        self._active_envs: dict[str, dict[str, str]] = {}
        self._active_cmds: dict[str, list[str]] = {}
        self._session_managers: dict[str, SessionLifecycleManager] = {}
        self._phase_tokens: dict[str, TokenAccumulator] = {}
        self._phase_auth_tokens: dict[str, tuple[int, int]] = {}  # authoritative (input, output)
        self._phase_artifact_ids: dict[str, list[str]] = {}
        self._phase_started_at: dict[str, datetime] = {}

    async def run(
        self,
        workflow_id: str,
        workflow_name: str,
        phases: list[ExecutablePhase],
        inputs: dict[str, Any],
        execution_id: str,
        repos: list[str] | None = None,
        expected_completion_at: datetime | None = None,
    ) -> WorkflowExecutionResult:
        """Execute a workflow using the Processor To-Do List pattern."""
        started_at = datetime.now(UTC)
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
        aggregate._handle_command(start_cmd)
        await self._save_and_sync(aggregate)

        phase_results: list[PhaseResult] = []
        all_artifact_ids: list[str] = []
        completed_phase_ids: list[str] = []
        phase_outputs: dict[str, str] = {}

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
            )

    async def _drain_todo_list(
        self,
        execution_id: str,
        aggregate: WorkflowExecutionAggregate,
        phase_map: dict[str, ExecutablePhase],
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        completed_phase_ids: list[str],
        phase_outputs: dict[str, str],
        repos: list[str] | None,
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
            )

    async def _dispatch(
        self,
        todo: TodoItem,
        aggregate: WorkflowExecutionAggregate,
        phase_map: dict[str, ExecutablePhase],
        phase_results: list[PhaseResult],
        all_artifact_ids: list[str],
        completed_phase_ids: list[str],
        phase_outputs: dict[str, str],
        repos: list[str] | None,
    ) -> None:
        """Dispatch a single to-do item to its handler."""
        assert todo.phase_id is not None
        phase = phase_map[todo.phase_id]
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
            await self._handle_complete_phase(
                todo,
                phase,
                aggregate,
                phase_results,
                completed_phase_ids,
            )

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
        self._session_managers.clear()
        for _pid, workspace_cm in list(self._active_workspace_cms.items()):
            try:
                await workspace_cm.__aexit__(None, None, None)
            except Exception:
                logger.exception("Error cleaning up workspace during cancel")
        self._active_workspace_cms.clear()
        self._active_workspaces.clear()
        self._active_envs.clear()
        self._active_cmds.clear()
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
            total_cost_usd=metrics.total_cost_usd,
            duration_seconds=metrics.total_duration_seconds,
            artifact_ids=all_artifact_ids,
        )
        aggregate._handle_command(complete_cmd)
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
    ) -> WorkflowExecutionResult:
        """Close open sessions, save failure event, and return failed result."""
        for _pid, mgr in list(self._session_managers.items()):
            await mgr.complete_failure(error_message=str(error))
        self._session_managers.clear()
        for _pid, workspace_cm in list(self._active_workspace_cms.items()):
            try:
                await workspace_cm.__aexit__(None, None, None)
            except Exception:
                logger.exception("Error cleaning up workspace during failure")
        self._active_workspace_cms.clear()
        self._active_workspaces.clear()
        self._active_envs.clear()
        self._active_cmds.clear()
        fail_cmd = FailExecutionCommand(
            execution_id=execution_id,
            error=str(error),
            error_type=type(error).__name__,
            failed_phase_id=None,
            completed_phases=len(completed_phase_ids),
            total_phases=len(phases),
        )
        try:
            aggregate._handle_command(fail_cmd)
            await self._save_and_sync(aggregate)
        except Exception as save_err:
            logger.error("Failed to save failure event: %s", save_err)
        return WorkflowExecutionResult(
            workflow_id=workflow_id,
            execution_id=execution_id,
            status="failed",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            phase_results=phase_results,
            artifact_ids=all_artifact_ids,
            metrics=ExecutionMetrics.from_results(phase_results),
            error_message=str(error),
        )

    async def _handle_provision(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        repos: list[str] | None,
        completed_phase_ids: list[str],
        phase_outputs: dict[str, str],
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
        aggregate._handle_command(start_cmd)

        session_mgr = SessionLifecycleManager(
            repository=self._session_repo,
            session_id=session_id,
            workflow_id=aggregate.workflow_id or "",
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            agent_provider=phase.agent_config.provider,
            agent_model=phase.agent_config.model,
        )
        await session_mgr.start()
        self._session_managers[todo.phase_id] = session_mgr
        self._phase_started_at[todo.phase_id] = datetime.now(UTC)

        artifacts = ArtifactCollector(
            self._artifact_repo,
            self._artifact_content_storage,
            self._artifact_query,
        )
        provision_handler = WorkspaceProvisionHandler(
            workspace_service=self._workspace_service,
            prompt_builder=self._prompt_builder,
            command_builder=self._command_builder,
        )
        result = await provision_handler.handle(
            todo=todo,
            phase=phase,
            workflow_id=aggregate.workflow_id or "",
            session_id=session_id,
            repos=repos,
            artifacts=artifacts,
            completed_phase_ids=completed_phase_ids,
            phase_outputs=phase_outputs,
            inputs=self._inputs,
        )

        self._active_workspaces[todo.phase_id] = result.workspace
        self._active_workspace_cms[todo.phase_id] = result.workspace_cm
        self._active_envs[todo.phase_id] = result.agent_env
        self._active_cmds[todo.phase_id] = result.claude_cmd
        aggregate._handle_command(result.command)
        await self._save_and_sync(aggregate)

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
        workflow_id = aggregate.workflow_id or ""
        timeout = phase.timeout_seconds or phase.agent_config.timeout_seconds

        collector = ObservabilityCollector(
            writer=self._observability_writer,
            session_id=session_id,
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workspace_id=getattr(workspace, "id", None),
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
        )

        recorder = ConversationRecorder(self._conversation_storage)
        await recorder.store(
            session_id=session_id,
            lines=result.stream_result.conversation_lines,
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workflow_id=workflow_id,
            model=phase.agent_config.model,
            input_tokens=result.tokens.input_tokens,
            output_tokens=result.tokens.output_tokens,
            started_at=self._phase_started_at.get(todo.phase_id, datetime.now(UTC)),
            success=result.command.exit_code == 0,
        )
        self._phase_tokens[todo.phase_id] = result.tokens
        # Store authoritative totals from CLI result event (includes cache tokens)
        self._phase_auth_tokens[todo.phase_id] = (
            result.command.input_tokens,
            result.command.output_tokens,
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

        aggregate._handle_command(result.command)
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
        aggregate._handle_command(cancel_cmd)
        await self._save_and_sync(aggregate)

    async def _handle_collect_artifacts(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        all_artifact_ids: list[str],
        phase_outputs: dict[str, str],
    ) -> None:
        """Dispatch COLLECT_ARTIFACTS."""
        assert todo.phase_id is not None
        workspace = self._active_workspaces[todo.phase_id]
        artifacts = ArtifactCollector(
            self._artifact_repo,
            self._artifact_content_storage,
            self._artifact_query,
        )
        collection_handler = ArtifactCollectionHandler(artifact_collector=artifacts)
        result = await collection_handler.handle(
            todo=todo,
            workspace=workspace,
            workflow_id=aggregate.workflow_id or "",
            session_id=todo.session_id or "",
            phase_name=phase.name,
            output_artifact_type=phase.output_artifact_type,
        )
        all_artifact_ids.extend(result.artifact_ids)
        self._phase_artifact_ids[todo.phase_id] = result.artifact_ids
        if result.first_content:
            phase_outputs[todo.phase_id] = result.first_content
        aggregate._handle_command(result.command)
        await self._save_and_sync(aggregate)

    async def _handle_complete_phase(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,  # noqa: ARG002
        aggregate: WorkflowExecutionAggregate,
        phase_results: list[PhaseResult],
        completed_phase_ids: list[str],
    ) -> None:
        """Dispatch COMPLETE_PHASE."""
        assert todo.phase_id is not None
        tokens = self._phase_tokens.pop(todo.phase_id, TokenAccumulator())
        auth_tokens = self._phase_auth_tokens.pop(todo.phase_id, None)
        artifact_ids = self._phase_artifact_ids.pop(todo.phase_id, [])
        started_at = self._phase_started_at.pop(todo.phase_id, datetime.now(UTC))

        # Prefer authoritative CLI result totals over per-turn accumulation
        final_input = auth_tokens[0] if auth_tokens else tokens.input_tokens
        final_output = auth_tokens[1] if auth_tokens else tokens.output_tokens
        final_total = final_input + final_output

        warnings: list[str] = []
        if final_input == 0 and final_output == 0:
            warnings.append("zero_tokens")
        if not artifact_ids:
            warnings.append("no_artifacts")

        result = PhaseResultBuilder.success(
            phase_id=todo.phase_id,
            started_at=started_at,
            session_id=todo.session_id or "",
            artifact_ids=artifact_ids,
            tokens=tokens,
            warnings=warnings,
        )
        phase_results.append(result)
        completed_phase_ids.append(todo.phase_id)
        duration = (datetime.now(UTC) - started_at).total_seconds()

        complete_cmd = CompletePhaseCommand(
            execution_id=todo.execution_id,
            workflow_id=aggregate.workflow_id or "",
            phase_id=todo.phase_id,
            session_id=todo.session_id,
            artifact_id=artifact_ids[0] if artifact_ids else None,
            input_tokens=final_input,
            output_tokens=final_output,
            total_tokens=final_total,
            cost_usd=tokens.estimate_cost(),
            duration_seconds=duration,
        )
        aggregate._handle_command(complete_cmd)
        await self._save_and_sync(aggregate)

        await self._finalize_phase(todo.phase_id, final_input, final_output, final_total, duration)

    async def _finalize_phase(
        self,
        phase_id: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        duration: float,
    ) -> None:
        """Complete session and clean up phase-local state."""
        session_mgr = self._session_managers.pop(phase_id, None)
        if session_mgr is not None:
            await session_mgr.complete_success(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                duration_seconds=duration,
                source="processor",
            )

        self._active_workspaces.pop(phase_id, None)
        self._active_envs.pop(phase_id, None)
        self._active_cmds.pop(phase_id, None)
        workspace_cm = self._active_workspace_cms.pop(phase_id, None)
        if workspace_cm is not None:
            await workspace_cm.__aexit__(None, None, None)

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
