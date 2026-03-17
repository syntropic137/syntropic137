"""WorkflowExecutionProcessor — reads to-do list, dispatches to handlers (ISS-196).

Replaces the imperative loop in WorkflowExecutionEngine. Zero business logic.
All decisions are made by the aggregate (phase sequencing) and the projection
(to-do list).

Uses in-process synchronous projection for immediate feedback after each save.
See AGENTS.md "Projection Consistency in Processor Loops".
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
    TodoAction,
    TodoItem,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ExecutionMetrics,
    PhaseDefinition,
    PhaseResult,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
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
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
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


# -- Protocols for dependency injection --

PromptBuilder = Callable[
    [ExecutablePhase, str, str, str | None, dict[str, str], dict[str, Any]],
    Awaitable[str],
]
"""async (phase, execution_id, workflow_id, repo_url, phase_outputs, inputs) -> prompt str"""

CommandBuilder = Callable[[ExecutablePhase, str], list[str]]
"""(phase, prompt) -> claude CLI command list"""


class TodoProjection(Protocol):
    """Protocol for the to-do list projection used by the processor."""

    def get_pending(self, execution_id: str) -> list[TodoItem]: ...


class ExecutionRepository(Protocol):
    """Repository protocol for WorkflowExecution aggregates."""

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None: ...
    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None: ...


class SessionRepository(Protocol):
    """Repository protocol for AgentSession aggregates."""

    async def save(self, aggregate: AgentSessionAggregate) -> None: ...


class ArtifactRepository(Protocol):
    """Repository protocol for Artifact aggregates."""

    async def save(self, aggregate: ArtifactAggregate) -> None: ...
    async def get_by_id(self, artifact_id: str) -> ArtifactAggregate | None: ...


@dataclass(frozen=True)
class WorkflowExecutionResult:
    """Immutable execution outcome."""

    workflow_id: str
    execution_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    phase_results: list[PhaseResult] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    error_message: str | None = None


class WorkflowExecutionProcessor:
    """Reads the to-do list and dispatches to handlers. Zero business logic.

    Uses an in-process synchronous projection for immediate feedback.
    After each aggregate save, uncommitted events are applied directly
    to the local todo projection.
    """

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

        # In-process synchronous projection — immediate feedback
        # Injected to avoid cross-slice import (VSA compliance)
        assert todo_projection is not None, "todo_projection is required"
        self._todo_projection: TodoProjection = todo_projection

        # Infrastructure state (not domain state — ephemeral)
        self._active_workspaces: dict[str, ManagedWorkspace] = {}
        self._active_workspace_cms: dict[str, AbstractAsyncContextManager[ManagedWorkspace]] = {}
        self._active_envs: dict[str, dict[str, str]] = {}
        self._active_cmds: dict[str, list[str]] = {}

        # Session lifecycle tracking (Fix #4)
        self._session_managers: dict[str, SessionLifecycleManager] = {}

        # Per-phase metrics tracking (Fix #5)
        self._phase_tokens: dict[str, TokenAccumulator] = {}
        self._phase_artifact_ids: dict[str, list[str]] = {}
        self._phase_started_at: dict[str, datetime] = {}

    async def run(
        self,
        workflow_id: str,
        workflow_name: str,
        phases: list[ExecutablePhase],
        inputs: dict[str, Any],
        execution_id: str,
        repo_url: str | None = None,
        expected_completion_at: datetime | None = None,
    ) -> WorkflowExecutionResult:
        """Execute a workflow using the Processor To-Do List pattern.

        Args:
            workflow_id: Workflow template ID
            workflow_name: Workflow name
            phases: Ordered list of executable phases
            inputs: Workflow inputs
            execution_id: Pre-generated execution ID
            repo_url: Optional repository URL
            expected_completion_at: For stale detection

        Returns:
            WorkflowExecutionResult with final state
        """
        started_at = datetime.now(UTC)
        self._inputs = inputs
        aggregate = WorkflowExecutionAggregate()

        # Build phase definitions for aggregate intelligence
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

        # Start execution
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

        # Tracking state derived from events during processing
        phase_results: list[PhaseResult] = []
        all_artifact_ids: list[str] = []
        completed_phase_ids: list[str] = []
        phase_outputs: dict[str, str] = {}

        try:
            # Main processor loop
            while True:
                todos = self._todo_projection.get_pending(execution_id)
                if not todos:
                    break

                todo = todos[0]
                await self._dispatch(
                    todo=todo,
                    aggregate=aggregate,
                    phase_map=phase_map,
                    phase_results=phase_results,
                    all_artifact_ids=all_artifact_ids,
                    completed_phase_ids=completed_phase_ids,
                    phase_outputs=phase_outputs,
                    repo_url=repo_url,
                )

            # Complete execution
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

        except Exception as e:
            # Complete any open sessions as failed (Fix #4)
            for _phase_id, mgr in list(self._session_managers.items()):
                await mgr.complete_failure(error_message=str(e))
            self._session_managers.clear()

            # Fail execution
            fail_cmd = FailExecutionCommand(
                execution_id=execution_id,
                error=str(e),
                error_type=type(e).__name__,
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
                error_message=str(e),
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
        repo_url: str | None,
    ) -> None:
        """Dispatch a single to-do item to its handler."""
        assert todo.phase_id is not None
        phase = phase_map[todo.phase_id]

        if todo.action == TodoAction.PROVISION_WORKSPACE:
            await self._handle_provision(
                todo, phase, aggregate, repo_url, completed_phase_ids, phase_outputs
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

        elif todo.action == TodoAction.COMPLETE_EXECUTION:
            pass  # Handled in the main loop after todos are empty

    async def _handle_provision(
        self,
        todo: TodoItem,
        phase: ExecutablePhase,
        aggregate: WorkflowExecutionAggregate,
        repo_url: str | None,
        completed_phase_ids: list[str],
        phase_outputs: dict[str, str],
    ) -> None:
        """Dispatch PROVISION_WORKSPACE."""
        assert todo.phase_id is not None
        session_id = str(uuid4())

        # Start phase in aggregate
        start_cmd = StartPhaseCommand(
            execution_id=todo.execution_id,
            workflow_id=aggregate.workflow_id or "",
            phase_id=todo.phase_id,
            phase_name=phase.name,
            phase_order=phase.order,
            session_id=session_id,
        )
        aggregate._handle_command(start_cmd)

        # Start session for observability
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

        # Create provision handler and run
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
            repo_url=repo_url,
            artifacts=artifacts,
            completed_phase_ids=completed_phase_ids,
            phase_outputs=phase_outputs,
            inputs=self._inputs,
        )

        # Store infrastructure state
        self._active_workspaces[todo.phase_id] = result.workspace
        self._active_workspace_cms[todo.phase_id] = result.workspace_cm
        self._active_envs[todo.phase_id] = result.agent_env
        self._active_cmds[todo.phase_id] = result.claude_cmd

        # Report to aggregate
        aggregate._handle_command(result.command)
        await self._save_and_sync(aggregate)

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

        # Create collector for Lane 2
        collector = ObservabilityCollector(
            writer=self._observability_writer,
            session_id=todo.session_id or "",
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workspace_id=getattr(workspace, "id", None),
            agent_model=phase.agent_config.model,
        )

        agent_handler = AgentExecutionHandler(controller=self._controller)
        result = await agent_handler.handle(
            todo=todo,
            workspace=workspace,
            agent_env=agent_env,
            claude_cmd=claude_cmd,
            session_id=todo.session_id or "",
            agent_model=phase.agent_config.model,
            timeout_seconds=phase.timeout_seconds or phase.agent_config.timeout_seconds,
            collector=collector,
        )

        # Store conversation log
        recorder = ConversationRecorder(self._conversation_storage)
        await recorder.store(
            session_id=todo.session_id or "",
            lines=result.stream_result.conversation_lines,
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            workflow_id=aggregate.workflow_id or "",
            model=phase.agent_config.model,
            input_tokens=result.tokens.input_tokens,
            output_tokens=result.tokens.output_tokens,
            started_at=self._phase_started_at.get(todo.phase_id, datetime.now(UTC)),
            success=result.command.exit_code == 0,
        )

        # Store tokens for phase result (Fix #5)
        self._phase_tokens[todo.phase_id] = result.tokens

        # Fail fast if agent CLI didn't run successfully
        if result.command.exit_code != 0:
            msg = (
                f"Agent execution failed for phase {todo.phase_id} "
                f"(exit_code={result.command.exit_code}, "
                f"tokens={result.tokens.input_tokens}+{result.tokens.output_tokens})"
            )
            logger.error(msg)
            raise RuntimeError(msg)

        # Report to aggregate
        aggregate._handle_command(result.command)
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

        # Report to aggregate — this triggers NextPhaseReady decision
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

        # Retrieve tracked per-phase data
        tokens = self._phase_tokens.pop(todo.phase_id, TokenAccumulator())
        artifact_ids = self._phase_artifact_ids.pop(todo.phase_id, [])
        started_at = self._phase_started_at.pop(todo.phase_id, datetime.now(UTC))

        # Build phase result with real data
        warnings: list[str] = []
        if tokens.input_tokens == 0 and tokens.output_tokens == 0:
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

        # Emit CompletePhaseCommand with real metrics
        complete_cmd = CompletePhaseCommand(
            execution_id=todo.execution_id,
            workflow_id=aggregate.workflow_id or "",
            phase_id=todo.phase_id,
            session_id=todo.session_id,
            artifact_id=artifact_ids[0] if artifact_ids else None,
            input_tokens=tokens.input_tokens,
            output_tokens=tokens.output_tokens,
            total_tokens=tokens.total_tokens,
            cost_usd=tokens.estimate_cost(),
            duration_seconds=duration,
        )
        aggregate._handle_command(complete_cmd)
        await self._save_and_sync(aggregate)

        # Complete session lifecycle (Fix #4)
        session_mgr = self._session_managers.pop(todo.phase_id, None)
        if session_mgr is not None:
            await session_mgr.complete_success(
                input_tokens=tokens.input_tokens,
                output_tokens=tokens.output_tokens,
                total_tokens=tokens.total_tokens,
                duration_seconds=duration,
                source="processor",
            )

        # Clean up infrastructure state
        self._active_workspaces.pop(todo.phase_id, None)
        self._active_envs.pop(todo.phase_id, None)
        self._active_cmds.pop(todo.phase_id, None)

        # Exit workspace context manager (destroys container)
        workspace_cm = self._active_workspace_cms.pop(todo.phase_id, None)
        if workspace_cm is not None:
            await workspace_cm.__aexit__(None, None, None)

    async def _save_and_sync(self, aggregate: WorkflowExecutionAggregate) -> None:
        """Save aggregate and synchronously update local projection.

        This is the key to immediate feedback — we don't wait for the
        persistent projection to catch up. Instead, we apply uncommitted
        events directly to our local projection instance.
        """
        # Read uncommitted events BEFORE save (save clears them)
        uncommitted = list(aggregate._uncommitted_events)

        await self._execution_repo.save(aggregate)

        # Apply to local projection for immediate feedback
        for envelope in uncommitted:
            event = envelope.event
            event_type = getattr(event, "event_type", type(event).__name__)
            # Convert to dict for projection handler
            if hasattr(event, "model_dump"):
                event_data = event.model_dump()
            elif hasattr(event, "to_dict"):
                event_data = event.to_dict()
            else:
                event_data = vars(event)
            # Use auto-dispatch — the projection has on_<snake_case> methods
            handler_name = self._event_type_to_handler(event_type)
            handler = getattr(self._todo_projection, handler_name, None)
            if handler:
                await handler(event_data)

    @staticmethod
    def _event_type_to_handler(event_type: str) -> str:
        """Convert CamelCase event type to on_snake_case handler name.

        E.g., 'WorkflowExecutionStarted' → 'on_workflow_execution_started'
        """
        import re

        # Insert underscore before uppercase letters (except first)
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", event_type).lower()
        return f"on_{snake}"
