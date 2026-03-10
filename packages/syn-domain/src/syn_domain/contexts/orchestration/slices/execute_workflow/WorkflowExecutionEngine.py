"""WorkflowExecutionEngine - orchestrates workflow execution across phases.

See ADR-023: Workspace-First Execution Model for architectural decisions.

Key requirements:
- WorkspaceService is REQUIRED - agents run inside isolated workspaces
- WorkflowExecutionRepository is REQUIRED - events persist via aggregate
- All events flow through WorkflowExecutionAggregate for consistency
"""

from __future__ import annotations

import logging
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
    ExecutionMetrics,
    ExecutionStatus,
    PhaseResult,
    PhaseStatus,
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
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.PhaseResultBuilder import (
    PhaseResultBuilder,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_prompt import (
    SYN_WORKSPACE_PROMPT,
)

if TYPE_CHECKING:
    from syn_adapters.agents.protocol import AgentProtocol as InstrumentedAgent  # Alias for compat
    from syn_adapters.control import ExecutionController
    from syn_adapters.conversations import ConversationStoragePort
    from syn_adapters.workspace_backends.service import WorkspaceService
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
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )


logger = logging.getLogger(__name__)


class WorkflowRepository(Protocol):
    """Repository protocol for Workflow aggregates."""

    async def get_by_id(self, workflow_id: str) -> WorkflowTemplateAggregate | None:
        """Get a workflow by ID."""
        ...

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        """Save the aggregate and its uncommitted events."""
        ...


class WorkflowExecutionRepository(Protocol):
    """Repository protocol for WorkflowExecution aggregates.

    Required per ADR-023: Workspace-First Execution Model.
    All execution events MUST be persisted via this repository.
    """

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        """Get an execution by ID."""
        ...

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        """Save the aggregate and persist uncommitted events to event store."""
        ...


class SessionRepository(Protocol):
    """Repository protocol for AgentSession aggregates."""

    async def save(self, aggregate: AgentSessionAggregate) -> None:
        """Save the session aggregate."""
        ...


class ArtifactRepository(Protocol):
    """Repository protocol for Artifact aggregates."""

    async def save(self, aggregate: ArtifactAggregate) -> None:
        """Save the artifact aggregate."""
        ...

    async def get_by_id(self, artifact_id: str) -> ArtifactAggregate | None:
        """Get an artifact by ID."""
        ...


# Type for agent factory function
AgentFactory = Callable[[str], "InstrumentedAgent"]


class WorkflowNotFoundError(Exception):
    """Raised when a workflow is not found."""

    def __init__(self, workflow_id: str) -> None:
        super().__init__(f"Workflow not found: {workflow_id}")
        self.workflow_id = workflow_id


class WorkflowExecutionError(Exception):
    """Raised when workflow execution fails."""

    def __init__(
        self,
        message: str,
        workflow_id: str,
        phase_id: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.workflow_id = workflow_id
        self.phase_id = phase_id
        self.__cause__ = cause


class WorkflowInterruptedError(Exception):
    """Raised when workflow execution is forcefully interrupted via SIGINT.

    Carries partial state captured at the time of interruption so the engine
    can persist a WorkflowInterruptedEvent with meaningful data.
    """

    def __init__(
        self,
        phase_id: str,
        reason: str | None = None,
        git_sha: str | None = None,
        partial_artifact_ids: list[str] | None = None,
        partial_input_tokens: int = 0,
        partial_output_tokens: int = 0,
    ) -> None:
        super().__init__(f"Execution interrupted in phase {phase_id}: {reason}")
        self.phase_id = phase_id
        self.reason = reason
        self.git_sha = git_sha
        self.partial_artifact_ids = partial_artifact_ids or []
        self.partial_input_tokens = partial_input_tokens
        self.partial_output_tokens = partial_output_tokens


@dataclass(frozen=True)
class WorkflowExecutionResult:
    """Result of a workflow execution.

    Immutable record of the execution outcome.
    """

    workflow_id: str
    execution_id: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: datetime | None = None
    phase_results: list[PhaseResult] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        """Check if execution completed successfully."""
        return self.status == ExecutionStatus.COMPLETED


@dataclass
class ExecutionContext:
    """Mutable context for tracking execution state.

    Note: Phase outputs are NO LONGER stored in-memory. They are persisted
    as artifacts and queried from the artifact projection when needed.
    This ensures crash recovery and audit trail (ADR-012, ADR-023).
    """

    workflow_id: str
    execution_id: str
    started_at: datetime
    inputs: dict[str, Any]
    repo_url: str | None = None  # Repository URL from workflow definition
    phase_results: list[PhaseResult] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    completed_phase_ids: list[str] = field(default_factory=list)  # For querying artifacts
    phase_outputs: dict[str, str] = field(
        default_factory=dict
    )  # In-memory cache for phase outputs (phase_id -> content)


class WorkflowExecutionEngine:
    """Orchestrates workflow execution across phases.

    IMPORTANT (ADR-023): This engine requires:
    - WorkspaceService: Agents run inside isolated workspaces
    - WorkflowExecutionRepository: Events persist via aggregate pattern

    Responsibilities:
    - Load workflow definition
    - Create isolated workspace for agent execution
    - Execute phases sequentially inside workspace
    - Manage phase input/output artifacts
    - Track execution metrics
    - Persist events via WorkflowExecutionAggregate

    Example:
        from syn_adapters.workspace_backends.service import WorkspaceService
        from syn_adapters.storage.repositories import get_workflow_execution_repository

        engine = WorkflowExecutionEngine(
            workflow_repository=workflow_repo,
            execution_repository=get_workflow_execution_repository(),
            workspace_service=WorkspaceService.create(),
            session_repository=session_repo,
            artifact_repository=artifact_repo,
            agent_factory=create_agent,
        )

        result = await engine.execute(
            workflow_id="workflow-123",
            inputs={"topic": "AI agents"},
        )
    """

    def __init__(
        self,
        workflow_repository: WorkflowRepository,
        execution_repository: WorkflowExecutionRepository,
        workspace_service: WorkspaceService,
        session_repository: SessionRepository,
        artifact_repository: ArtifactRepository,
        agent_factory: AgentFactory,
        artifact_query_service: ArtifactQueryServiceProtocol | None = None,
        observability_writer: Any | None = None,
        artifact_content_storage: ArtifactContentStoragePort | None = None,
        conversation_storage: ConversationStoragePort | None = None,
        controller: ExecutionController | None = None,
    ) -> None:
        """Initialize the workflow execution engine.

        Args:
            workflow_repository: Repository for Workflow aggregates
            execution_repository: Repository for WorkflowExecution aggregates (REQUIRED)
            workspace_service: Service for creating isolated workspaces (REQUIRED)
            session_repository: Repository for AgentSession aggregates
            artifact_repository: Repository for Artifact aggregates
            agent_factory: Factory for creating instrumented agents
            artifact_query_service: Service for querying artifacts (REQUIRED for
                multi-phase workflows). If None, phase outputs cannot be injected
                into subsequent phase prompts.
            observability_writer: ObservabilityWriter for TimescaleDB (ADR-026)
            artifact_content_storage: Storage for artifact content in object storage
                (MinIO/S3). If None, content stored only in event store. (ADR-012)
            conversation_storage: Storage for full conversation logs in S3/MinIO (ADR-035)

        Raises:
            ValueError: If execution_repository or workspace_service is None
        """
        if execution_repository is None:
            raise ValueError(
                "execution_repository is required per ADR-023. "
                "Use get_workflow_execution_repository() from syn_adapters.storage.repositories."
            )
        if workspace_service is None:
            raise ValueError(
                "workspace_service is required per ADR-023. "
                "Use WorkspaceService.create() from syn_adapters.workspace_backends.service."
            )

        self._workflows = workflow_repository
        self._executions = execution_repository
        self._workspace_service = workspace_service
        self._sessions = session_repository
        self._artifacts = artifact_repository
        self._agent_factory = agent_factory
        self._artifact_query = artifact_query_service
        self._observability_writer = observability_writer
        self._artifact_content_storage = artifact_content_storage
        self._conversation_storage = conversation_storage
        self._controller = controller

    async def _record_observation(
        self,
        observation_type: ObservationType | str,
        session_id: str,
        data: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        """Record an agent observation to TimescaleDB.

        Args:
            observation_type: Type of observation (enum or raw string from hook events)
            session_id: The session ID
            data: Observation data (JSONB)
            execution_id: Optional execution ID
            phase_id: Optional phase ID
            workspace_id: Optional workspace ID
        """
        if self._observability_writer is None:
            return

        obs_type_str = (
            observation_type.value
            if isinstance(observation_type, ObservationType)
            else str(observation_type)
        )

        await self._observability_writer.record_observation(
            session_id=session_id,
            observation_type=obs_type_str,
            data=data,
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )

    async def _get_container_git_sha(self, workspace: Any) -> str | None:
        """Get the current git HEAD SHA from inside the workspace container.

        Used to capture the exact code state at the time of interruption for
        audit trail and reproducibility.

        Returns None if git is unavailable or command fails (non-fatal).
        """
        try:
            result = await workspace.execute(
                ["git", "rev-parse", "HEAD"],
                working_directory="/workspace",
                timeout_seconds=5,
            )
            if result.exit_code == 0:
                return result.stdout.strip() or None
        except Exception as e:
            logger.debug("_get_container_git_sha: failed: %s", e)
        return None

    async def execute(
        self,
        workflow_id: str,
        inputs: dict[str, Any],
        execution_id: str | None = None,
        use_container: bool = True,
        tenant_id: str | None = None,
    ) -> WorkflowExecutionResult:
        """Execute a workflow from start to finish.

        Per ADR-021/ADR-023/ADR-029, agents execute inside isolated environments
        using Claude Code CLI. All events are persisted via aggregates.

        Args:
            workflow_id: ID of the workflow to execute.
            inputs: Initial input variables for the workflow.
            execution_id: Optional custom execution ID.
            use_container: If True (default), run in isolated container.
                DEPRECATED: The SDK-based host mode (use_container=False) is
                legacy and will be removed. All execution should use container
                mode with the appropriate isolation backend (ADR-021).
            tenant_id: Tenant ID for multi-tenant token vending.

        Returns:
            WorkflowExecutionResult with status and artifacts.

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist.
            WorkflowExecutionError: If execution fails.
        """
        # 1. Load workflow
        workflow = await self._workflows.get_by_id(workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(workflow_id)

        # 2. Initialize execution context
        # Get repo URL from aggregate's private attribute (set from workflow definition)
        repo_url = getattr(workflow, "_repository_url", None)

        # Substitute template variables in repo_url using workflow inputs.
        # Trigger-based workflows use templates like "https://github.com/{{repository}}"
        # where {{repository}} is resolved from the webhook payload at dispatch time.
        if repo_url and inputs:
            for key, value in inputs.items():
                repo_url = repo_url.replace(f"{{{{{key}}}}}", str(value))

        ctx = ExecutionContext(
            workflow_id=workflow_id,
            execution_id=execution_id or str(uuid4()),
            started_at=datetime.now(UTC),
            inputs=inputs,
            repo_url=repo_url,
        )

        # 3. Create execution aggregate and emit started event
        aggregate = WorkflowExecutionAggregate()
        start_cmd = StartExecutionCommand(
            execution_id=ctx.execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow.name or "Unknown",
            total_phases=len(workflow.phases),
            inputs=inputs,
        )
        aggregate._handle_command(start_cmd)
        await self._executions.save(aggregate)

        logger.info(
            "Workflow execution started: %s (execution: %s)",
            workflow_id,
            ctx.execution_id,
        )

        # 4. Execute phases
        # Agent execution modes:
        # - HOST_PROCESS: Agent SDK runs directly (current default, for development)
        # - CONTAINER: Agent runs inside isolated workspace with sidecar
        #
        # When use_container_execution=True:
        #   1. Create workspace via self._router.create()
        #   2. Start sidecar proxy (for token injection)
        #   3. Inject artifacts from previous phases
        #   4. Write task.json with phase config
        #   5. Execute Claude CLI via workspace.stream() (ADR-029)
        #   6. Parse JSONL events and update aggregate
        #   7. Collect artifacts for next phase
        #   8. Destroy workspace (stateless)
        #
        # See ADR-023: Workspace-First Execution Model
        try:
            phases = self._get_executable_phases(workflow)
            for phase in sorted(phases, key=lambda p: p.order):
                if use_container:
                    # Container mode: agent runs inside isolated workspace with sidecar
                    result = await self._execute_phase_in_container(
                        phase=phase,
                        ctx=ctx,
                        aggregate=aggregate,
                        tenant_id=tenant_id,
                    )
                    ctx.phase_results.append(result)
                    if result.artifact_id:
                        ctx.artifact_ids.append(result.artifact_id)
                    ctx.completed_phase_ids.append(phase.phase_id)
                else:
                    # Host mode: agent SDK runs directly in host process
                    await self._execute_phase(workflow, phase, ctx, aggregate)
                # Save after each phase for partial progress persistence
                await self._executions.save(aggregate)

            # 5. Emit completion event and save
            metrics = ExecutionMetrics.from_results(ctx.phase_results)
            complete_cmd = CompleteExecutionCommand(
                execution_id=ctx.execution_id,
                completed_phases=metrics.completed_phases,
                total_phases=metrics.total_phases,
                total_input_tokens=metrics.total_input_tokens,
                total_output_tokens=metrics.total_output_tokens,
                total_cost_usd=metrics.total_cost_usd,
                duration_seconds=metrics.total_duration_seconds,
                artifact_ids=ctx.artifact_ids,
            )
            aggregate._handle_command(complete_cmd)
            await self._executions.save(aggregate)

            logger.info(
                "Workflow execution completed: %s (phases: %d, tokens: %d)",
                workflow_id,
                metrics.completed_phases,
                metrics.total_tokens,
            )

            return WorkflowExecutionResult(
                workflow_id=workflow_id,
                execution_id=ctx.execution_id,
                status=ExecutionStatus.COMPLETED,
                started_at=ctx.started_at,
                completed_at=datetime.now(UTC),
                phase_results=ctx.phase_results,
                artifact_ids=ctx.artifact_ids,
                metrics=metrics,
            )

        except WorkflowInterruptedError as e:
            # User-initiated cancel: emit ExecutionCancelledEvent → status = "cancelled"
            from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
                CancelExecutionCommand,
            )

            cancel_cmd = CancelExecutionCommand(
                execution_id=ctx.execution_id,
                phase_id=e.phase_id,
                reason=e.reason,
            )
            aggregate._handle_command(cancel_cmd)
            await self._executions.save(aggregate)

            logger.info(
                "Workflow execution cancelled: %s (phase: %s, reason: %s)",
                workflow_id,
                e.phase_id,
                e.reason,
            )

            metrics = ExecutionMetrics.from_results(ctx.phase_results)
            return WorkflowExecutionResult(
                workflow_id=workflow_id,
                execution_id=ctx.execution_id,
                status=ExecutionStatus.CANCELLED,
                started_at=ctx.started_at,
                completed_at=datetime.now(UTC),
                phase_results=ctx.phase_results,
                artifact_ids=ctx.artifact_ids,
                metrics=metrics,
                error_message=e.reason or "Cancelled by user",
            )

        except Exception as e:
            # 6. Handle failure - emit failed event and save
            metrics = ExecutionMetrics.from_results(ctx.phase_results)
            failed_phase_id = None
            if isinstance(e, WorkflowExecutionError):
                failed_phase_id = e.phase_id

            fail_cmd = FailExecutionCommand(
                execution_id=ctx.execution_id,
                error=str(e),
                error_type=type(e).__name__,
                failed_phase_id=failed_phase_id,
                completed_phases=metrics.completed_phases,
                total_phases=len(workflow.phases),
            )
            aggregate._handle_command(fail_cmd)
            await self._executions.save(aggregate)

            logger.error(
                "Workflow execution failed: %s (phase: %s, error: %s)",
                workflow_id,
                failed_phase_id,
                str(e),
            )

            return WorkflowExecutionResult(
                workflow_id=workflow_id,
                execution_id=ctx.execution_id,
                status=ExecutionStatus.FAILED,
                started_at=ctx.started_at,
                completed_at=datetime.now(UTC),
                phase_results=ctx.phase_results,
                artifact_ids=ctx.artifact_ids,
                metrics=metrics,
                error_message=str(e),
            )

    def _get_executable_phases(self, workflow: WorkflowTemplateAggregate) -> list[ExecutablePhase]:
        """Convert workflow phases to executable phases.

        In a real implementation, this would include full agent config
        and prompt templates. For now, creates basic executable phases.
        """
        executable_phases = []
        for phase in workflow.phases:
            executable_phases.append(
                ExecutablePhase(
                    phase_id=phase.phase_id,
                    name=phase.name,
                    order=phase.order,
                    description=phase.description,
                    prompt_template=phase.prompt_template or "",
                    output_artifact_type=phase.output_artifact_types[0]
                    if phase.output_artifact_types
                    else "text",
                    timeout_seconds=phase.timeout_seconds,
                )
            )
        return executable_phases

    async def _execute_phase(
        self,
        _workflow: WorkflowTemplateAggregate,
        phase: ExecutablePhase,
        ctx: ExecutionContext,
        aggregate: WorkflowExecutionAggregate,
    ) -> None:
        """Execute a single phase.

        1. Emit phase started via aggregate
        2. Build prompt from template and inputs
        3. Execute agent
        4. Create artifact
        5. Emit phase completed via aggregate
        6. Track session with token data
        """
        from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
            SessionLifecycleManager,
        )

        phase_started_at = datetime.now(UTC)
        session_id = str(uuid4())

        session_mgr = SessionLifecycleManager(
            repository=self._sessions,
            session_id=session_id,
            workflow_id=ctx.workflow_id,
            execution_id=ctx.execution_id,
            phase_id=phase.phase_id,
            agent_provider=phase.agent_config.provider,
            agent_model=phase.agent_config.model,
        )
        await session_mgr.start()

        # Emit phase started via aggregate
        start_phase_cmd = StartPhaseCommand(
            execution_id=ctx.execution_id,
            workflow_id=ctx.workflow_id,
            phase_id=phase.phase_id,
            phase_name=phase.name,
            phase_order=phase.order,
            session_id=session_id,
        )
        aggregate._handle_command(start_phase_cmd)
        logger.info("Phase started: %s (workflow: %s)", phase.phase_id, ctx.workflow_id)

        try:
            # Get instrumented agent
            agent = self._agent_factory(phase.agent_config.provider)
            agent.set_session_context(
                session_id=session_id,
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
            )

            # Build prompt (queries previous phase artifacts from DB)
            prompt = await self._build_prompt(phase, ctx)

            # Import here to avoid circular imports
            from syn_adapters.agents import AgentConfig, AgentMessage, AgentRole

            # Validate prompt is not empty (fail fast)
            if not prompt.strip():
                raise WorkflowExecutionError(
                    message=(
                        f"Phase '{phase.phase_id}' has empty prompt - "
                        "workflow phases MUST have a prompt_template defined"
                    ),
                    workflow_id=ctx.workflow_id,
                    phase_id=phase.phase_id,
                )

            # Validate model is set (fail fast - no mock defaults)
            if not phase.agent_config.model:
                raise WorkflowExecutionError(
                    message=(
                        f"Phase '{phase.phase_id}' has no model configured - "
                        "set model in agent_config (e.g., 'claude-sonnet')"
                    ),
                    workflow_id=ctx.workflow_id,
                    phase_id=phase.phase_id,
                )

            # Execute agent
            response = await agent.complete(
                messages=[AgentMessage(role=AgentRole.USER, content=prompt)],
                config=AgentConfig(
                    model=phase.agent_config.model,
                    max_tokens=phase.agent_config.max_tokens,
                    temperature=phase.agent_config.temperature,
                    timeout_seconds=phase.timeout_seconds or phase.agent_config.timeout_seconds,
                ),
            )

            # Create artifact linked to this execution run
            artifact_id = str(uuid4())
            artifact_collector = ArtifactCollector(
                self._artifacts, self._artifact_content_storage, self._artifact_query
            )
            await artifact_collector.create_artifact(
                artifact_id=artifact_id,
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
                execution_id=ctx.execution_id,
                session_id=session_id,
                artifact_type=phase.output_artifact_type,
                content=response.content,
                title=f"{phase.name} Output",
            )

            # Track completed phase for artifact queries
            ctx.completed_phase_ids.append(phase.phase_id)
            ctx.artifact_ids.append(artifact_id)

            # Store in in-memory cache for immediate use by next phase
            # This avoids eventual consistency issues with projection queries
            if response.content:
                ctx.phase_outputs[phase.phase_id] = response.content
                logger.info(
                    "Phase output cached for injection: %s (%d chars)",
                    phase.phase_id,
                    len(response.content),
                )

            # Record phase result
            phase_completed_at = datetime.now(UTC)
            duration = (phase_completed_at - phase_started_at).total_seconds()

            result = PhaseResult(
                phase_id=phase.phase_id,
                status=PhaseStatus.COMPLETED,
                started_at=phase_started_at,
                completed_at=phase_completed_at,
                artifact_id=artifact_id,
                session_id=session_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                total_tokens=response.total_tokens,
                cost_usd=Decimal(str(response.cost_estimate)),
            )
            ctx.phase_results.append(result)

            # Emit phase completed via aggregate
            complete_phase_cmd = CompletePhaseCommand(
                execution_id=ctx.execution_id,
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
                session_id=session_id,
                artifact_id=artifact_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                total_tokens=response.total_tokens,
                cost_usd=Decimal(str(response.cost_estimate)),
                duration_seconds=duration,
            )
            aggregate._handle_command(complete_phase_cmd)

            # Record token usage and complete session
            await session_mgr.complete_success(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                total_tokens=response.total_tokens,
                duration_seconds=duration,
                source="direct_execution",
            )

            logger.info(
                "Phase completed: %s (success: True, tokens: %d)",
                phase.phase_id,
                response.total_tokens,
            )

        except Exception as e:
            # Record failed phase
            phase_completed_at = datetime.now(UTC)
            duration = (phase_completed_at - phase_started_at).total_seconds()

            result = PhaseResult(
                phase_id=phase.phase_id,
                status=PhaseStatus.FAILED,
                started_at=phase_started_at,
                completed_at=phase_completed_at,
                session_id=session_id,
                error_message=str(e),
            )
            ctx.phase_results.append(result)

            # Complete session with failure
            await session_mgr.complete_failure(error_message=str(e))

            # Note: We don't emit PhaseCompleted for failures
            # The FailExecutionCommand in execute() will capture the failure
            logger.info(
                "Phase failed: %s (error: %s)",
                phase.phase_id,
                str(e),
            )

            # Re-raise to stop workflow
            raise WorkflowExecutionError(
                message=f"Phase {phase.phase_id} failed: {e}",
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
                cause=e,
            ) from e

    async def _build_prompt(self, phase: ExecutablePhase, ctx: ExecutionContext) -> str:
        """Build the prompt for a phase.

        Substitutes template variables with:
        - Built-in variables (execution_id, repo_url, workflow_id, phase_id)
        - Initial workflow inputs
        - Previous phase outputs (queried from DB via ArtifactQueryService)

        Note: Phase outputs are retrieved from the artifact projection, NOT from
        an in-memory dict. This ensures crash recovery and audit trail.
        """
        prompt = phase.prompt_template

        # Substitute built-in variables
        prompt = prompt.replace("{{execution_id}}", ctx.execution_id)
        prompt = prompt.replace("{{workflow_id}}", ctx.workflow_id)
        prompt = prompt.replace("{{phase_id}}", phase.phase_id)
        if ctx.repo_url:
            prompt = prompt.replace("{{repo_url}}", ctx.repo_url)

        # Substitute initial inputs
        for key, value in ctx.inputs.items():
            prompt = prompt.replace(f"{{{{{key}}}}}", str(value))

        # Substitute previous phase outputs (in-memory cache first, then DB)
        if ctx.completed_phase_ids:
            # 1. Get from in-memory cache first (immediate, no eventual consistency)
            phase_outputs: dict[str, str] = {}
            for pid in ctx.completed_phase_ids:
                if pid in ctx.phase_outputs:
                    phase_outputs[pid] = ctx.phase_outputs[pid]

            # 2. Query projection for any missing phases
            missing_phases = [pid for pid in ctx.completed_phase_ids if pid not in phase_outputs]
            if missing_phases and self._artifact_query:
                projection_outputs = await self._artifact_query.get_for_phase_injection(
                    execution_id=ctx.execution_id,
                    completed_phase_ids=missing_phases,
                )
                phase_outputs.update(projection_outputs)
            elif missing_phases and not self._artifact_query:
                logger.warning(
                    "artifact_query_service not configured - some phase outputs cannot be "
                    "injected into prompt. Missing phases: %s",
                    missing_phases,
                )

            # 3. Substitute into prompt
            for phase_id, content in phase_outputs.items():
                # Support both {{phase_id}} and {{phase_id_output}} patterns
                prompt = prompt.replace(f"{{{{{phase_id}}}}}", content)
                prompt = prompt.replace(f"{{{{{phase_id}_output}}}}", content)

        return prompt

    async def _execute_phase_in_container(
        self,
        phase: ExecutablePhase,
        ctx: ExecutionContext,
        aggregate: WorkflowExecutionAggregate,
        tenant_id: str | None = None,  # noqa: ARG002 — reserved for multi-tenant routing
    ) -> PhaseResult:
        """Execute a phase inside an isolated container with sidecar proxy.

        This implements the full agent-in-container pattern per ADR-023.

        Contract:
            On success: RETURNS PhaseResult. Caller appends to ctx.phase_results,
            ctx.completed_phase_ids, and ctx.artifact_ids.
            On failure: Appends failure PhaseResult to ctx.phase_results, then raises
            WorkflowExecutionError. Caller should NOT append again.
            On interrupt: Extends ctx.artifact_ids with partial artifacts, then raises
            WorkflowInterruptedError.
        """
        from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
            SessionLifecycleManager,
        )

        phase_started_at = datetime.now(UTC)
        session_id = str(uuid4())

        # Emit phase started
        start_cmd = StartPhaseCommand(
            execution_id=ctx.execution_id,
            workflow_id=ctx.workflow_id,
            phase_id=phase.phase_id,
            phase_name=phase.name,
            phase_order=phase.order,
            session_id=session_id,
        )
        aggregate._handle_command(start_cmd)
        logger.info(
            "Phase started (container mode): %s (workflow: %s)",
            phase.phase_id,
            ctx.workflow_id,
        )

        # Create session aggregate for detailed observability
        session_mgr = SessionLifecycleManager(
            repository=self._sessions,
            session_id=session_id,
            workflow_id=ctx.workflow_id,
            execution_id=ctx.execution_id,
            phase_id=phase.phase_id,
            agent_provider=phase.agent_config.provider,
            agent_model=phase.agent_config.model,
        )
        await session_mgr.start()

        # Create collaborators
        tokens = TokenAccumulator()
        subagents = SubagentTracker()
        recorder = ConversationRecorder(self._conversation_storage)
        artifacts = ArtifactCollector(
            self._artifacts, self._artifact_content_storage, self._artifact_query
        )

        # Track conversation lines for failure handling (stream_result may not exist
        # if exception occurs before stream processing)
        _conversation_lines: list[str] = []  # default for error path if process_stream() raises

        try:
            async with self._workspace_service.create_workspace(
                execution_id=ctx.execution_id,
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
                with_sidecar=False,
                inject_tokens=False,
            ) as workspace:
                # Run setup, inject artifacts, build command, validate auth
                agent_env, claude_cmd = await self._setup_workspace_for_phase(
                    workspace=workspace,
                    phase=phase,
                    ctx=ctx,
                    session_id=session_id,
                    artifacts=artifacts,
                )

                # Process event stream
                processor = EventStreamProcessor(
                    tokens=tokens,
                    subagents=subagents,
                    observability=self._observability_writer,
                    controller=self._controller,
                    execution_id=ctx.execution_id,
                    phase_id=phase.phase_id,
                    session_id=session_id,
                    workspace_id=getattr(workspace, "id", None),
                    agent_model=phase.agent_config.model,
                )

                stream_result = await processor.process_stream(
                    workspace.stream(
                        claude_cmd,
                        timeout_seconds=phase.timeout_seconds or 300,
                        environment=agent_env,
                    ),
                    workspace,
                )
                _conversation_lines = stream_result.conversation_lines

                # Handle interrupt (raises WorkflowInterruptedError)
                if stream_result.interrupt_requested:
                    await self._handle_stream_interrupt(
                        workspace=workspace,
                        stream_result=stream_result,
                        phase=phase,
                        ctx=ctx,
                        session_id=session_id,
                        tokens=tokens,
                        artifacts=artifacts,
                        recorder=recorder,
                        phase_started_at=phase_started_at,
                    )

                # Validate stream outcome (raises WorkflowExecutionError)
                self._validate_stream_result(
                    stream_result, workspace, ctx.workflow_id, phase.phase_id
                )

                # Store conversation log (ADR-035)
                await recorder.store(
                    session_id=session_id,
                    lines=stream_result.conversation_lines,
                    execution_id=ctx.execution_id,
                    phase_id=phase.phase_id,
                    workflow_id=ctx.workflow_id,
                    model=phase.agent_config.model,
                    input_tokens=tokens.input_tokens,
                    output_tokens=tokens.output_tokens,
                    started_at=phase_started_at,
                    success=True,
                )

                # Collect output artifacts (ADR-036)
                collected = await artifacts.collect_from_workspace(
                    workspace=workspace,
                    workflow_id=ctx.workflow_id,
                    phase_id=phase.phase_id,
                    execution_id=ctx.execution_id,
                    session_id=session_id,
                    phase_name=phase.name,
                    output_artifact_type=phase.output_artifact_type,
                )
                ctx.artifact_ids.extend(collected.artifact_ids)

                # Cache first artifact for phase-to-phase injection
                if collected.first_content:
                    ctx.phase_outputs[phase.phase_id] = collected.first_content
                    logger.info(
                        "Phase output cached for injection: %s (%d chars)",
                        phase.phase_id,
                        len(collected.first_content),
                    )

                # Capture values needed after workspace exit
                _line_count = stream_result.line_count
                _collected_artifact_ids = collected.artifact_ids

            # Workspace destroyed here (context manager exit)

            if _line_count == 0 and tokens.total_tokens == 0:
                raise WorkflowExecutionError(
                    message=(
                        "Agent produced no output. Possible causes: "
                        "authentication failure, missing credentials, or agent crash."
                    ),
                    workflow_id=ctx.workflow_id,
                    phase_id=phase.phase_id,
                )

            # Build success result
            result = PhaseResultBuilder.success(
                phase_id=phase.phase_id,
                started_at=phase_started_at,
                session_id=session_id,
                artifact_ids=_collected_artifact_ids,
                tokens=tokens,
            )

            # Emit phase completed
            duration = (
                (result.completed_at - phase_started_at).total_seconds()
                if result.completed_at
                else 0.0
            )
            complete_cmd = CompletePhaseCommand(
                execution_id=ctx.execution_id,
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
                session_id=session_id,
                artifact_id=_collected_artifact_ids[0] if _collected_artifact_ids else None,
                input_tokens=tokens.input_tokens,
                output_tokens=tokens.output_tokens,
                total_tokens=tokens.total_tokens,
                cost_usd=result.cost_usd,
                duration_seconds=duration,
            )
            aggregate._handle_command(complete_cmd)

            # Record token usage and complete session
            await session_mgr.complete_success(
                input_tokens=tokens.input_tokens,
                output_tokens=tokens.output_tokens,
                total_tokens=tokens.total_tokens,
                duration_seconds=duration,
                source="container_execution",
            )

            logger.info(
                "Phase completed (container mode): %s (tokens: %d)",
                phase.phase_id,
                tokens.total_tokens,
            )

            return result

        except WorkflowInterruptedError as _interrupted_err:
            # Complete the session as cancelled before propagating
            await session_mgr.complete_cancelled(
                reason=_interrupted_err.reason or "Interrupted by user",
            )
            raise

        except Exception as e:
            # Build failure result
            result = PhaseResultBuilder.failure(
                phase_id=phase.phase_id,
                started_at=phase_started_at,
                session_id=session_id,
                error_message=str(e),
            )
            ctx.phase_results.append(result)

            # Store conversation log even on failure (ADR-035)
            await recorder.store(
                session_id=session_id,
                lines=_conversation_lines,
                execution_id=ctx.execution_id,
                phase_id=phase.phase_id,
                workflow_id=ctx.workflow_id,
                model=phase.agent_config.model,
                input_tokens=tokens.input_tokens,
                output_tokens=tokens.output_tokens,
                started_at=phase_started_at,
                success=False,
            )

            # Complete session aggregate (failure)
            await session_mgr.complete_failure(error_message=str(e))

            logger.error(
                "Phase failed (container mode): %s (error: %s)",
                phase.phase_id,
                str(e),
            )

            raise WorkflowExecutionError(
                message=f"Phase {phase.phase_id} failed in container: {e}",
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
                cause=e,
            ) from e

    async def _setup_workspace_for_phase(
        self,
        workspace: Any,
        phase: ExecutablePhase,
        ctx: ExecutionContext,
        session_id: str,
        artifacts: ArtifactCollector,
    ) -> tuple[dict[str, str], list[str]]:
        """Set up workspace for phase execution (ADR-024).

        Handles: secrets creation, setup phase, artifact injection,
        prompt building, auth validation, and environment construction.

        Returns:
            Tuple of (agent_env, claude_cmd).
        """
        from syn_adapters.workspace_backends.service import SetupPhaseSecrets

        _SKIP_URLS = {
            "https://github.com/placeholder/not-configured",
            "https://github.com/example/repo",
        }
        _repo: str | None = None
        if ctx.repo_url:
            _normalized = ctx.repo_url.rstrip("/")
            if _normalized not in _SKIP_URLS:
                _parts = _normalized.split("/")
                if len(_parts) >= 2:
                    _repo = f"{_parts[-2]}/{_parts[-1]}"

        secrets = await SetupPhaseSecrets.create(
            repository=_repo,
            require_github=_repo is not None,
        )

        setup_result = await workspace.run_setup_phase(secrets)
        if setup_result.exit_code != 0:
            raise WorkflowExecutionError(
                message=f"Setup phase failed: {setup_result.stderr}",
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
            )
        logger.info("Setup phase completed, secrets cleared")

        # Inject input artifacts from previous phases (ADR-036)
        await artifacts.inject_from_previous_phases(workspace, ctx)

        # Build prompt and CLI command
        prompt = await self._build_prompt(phase, ctx)
        claude_cmd = self._build_claude_command(phase, prompt)

        # Validate Claude authentication
        if not secrets.claude_code_oauth_token and not secrets.anthropic_api_key:
            raise WorkflowExecutionError(
                message=(
                    "No Claude authentication configured. "
                    "Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in environment."
                ),
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
            )

        agent_env: dict[str, str] = {
            "CLAUDE_SESSION_ID": session_id,
        }
        if secrets.claude_code_oauth_token:
            agent_env["CLAUDE_CODE_OAUTH_TOKEN"] = secrets.claude_code_oauth_token
        if secrets.anthropic_api_key:
            agent_env["ANTHROPIC_API_KEY"] = secrets.anthropic_api_key

        return agent_env, claude_cmd

    async def _handle_stream_interrupt(
        self,
        workspace: Any,
        stream_result: Any,
        phase: ExecutablePhase,
        ctx: ExecutionContext,
        session_id: str,
        tokens: TokenAccumulator,
        artifacts: ArtifactCollector,
        recorder: ConversationRecorder,
        phase_started_at: datetime,
    ) -> None:
        """Handle an interrupted stream by collecting partial state and raising.

        Always raises WorkflowInterruptedError.
        """
        try:
            git_sha = await self._get_container_git_sha(workspace)
        except Exception as git_err:
            logger.warning(
                "Failed to collect git SHA during interrupt for %s: %s",
                session_id,
                git_err,
            )
            git_sha = None

        partial_artifact_ids = await artifacts.collect_partial(
            workspace=workspace,
            workflow_id=ctx.workflow_id,
            phase_id=phase.phase_id,
            execution_id=ctx.execution_id,
            session_id=session_id,
            phase_name=phase.name,
            output_artifact_type=phase.output_artifact_type,
        )
        ctx.artifact_ids.extend(partial_artifact_ids)

        await recorder.store(
            session_id=session_id,
            lines=stream_result.conversation_lines,
            execution_id=ctx.execution_id,
            phase_id=phase.phase_id,
            workflow_id=ctx.workflow_id,
            model=phase.agent_config.model,
            input_tokens=tokens.input_tokens,
            output_tokens=tokens.output_tokens,
            started_at=phase_started_at,
            success=False,
        )

        raise WorkflowInterruptedError(
            phase_id=phase.phase_id,
            reason=stream_result.interrupt_reason,
            git_sha=git_sha,
            partial_artifact_ids=partial_artifact_ids,
            partial_input_tokens=tokens.input_tokens,
            partial_output_tokens=tokens.output_tokens,
        )

    @staticmethod
    def _validate_stream_result(
        stream_result: Any,
        workspace: Any,
        workflow_id: str,
        phase_id: str,
    ) -> None:
        """Validate stream completed successfully. Raises WorkflowExecutionError on failure."""
        exit_code = workspace.last_stream_exit_code
        if exit_code is not None and exit_code != 0:
            raise WorkflowExecutionError(
                message=(
                    f"Agent process exited with code {exit_code}. Check agent logs for details."
                ),
                workflow_id=workflow_id,
                phase_id=phase_id,
            )

        task_result = stream_result.agent_task_result
        if task_result is not None and not task_result.get("success", True):
            comments = task_result.get("comments", "Agent reported task failure")
            raise WorkflowExecutionError(
                message=comments,
                workflow_id=workflow_id,
                phase_id=phase_id,
            )

    def _build_claude_command(self, phase: ExecutablePhase, prompt: str) -> list[str]:
        """Build the Claude CLI command with plugin discovery."""
        claude_args = [
            "claude",
            "--print",
            "--verbose",
            "--append-system-prompt",
            SYN_WORKSPACE_PROMPT,
            prompt,
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
        ]

        if phase.agent_config.allowed_tools:
            claude_args.extend(
                [
                    "--allowedTools",
                    ",".join(phase.agent_config.allowed_tools),
                ]
            )

        # Wrap in sh -c for dynamic plugin discovery
        _quoted_args = " ".join(shlex.quote(a) for a in claude_args)
        _plugin_scan = (
            'PLUGIN_FLAGS=""; '
            'PLUGINS_DIR="${AGENTIC_PLUGINS_DIR:-/opt/agentic/plugins}"; '
            'if [ -d "$PLUGINS_DIR" ]; then '
            '  for d in "$PLUGINS_DIR"/*/; do '
            '    if [ -f "${d}.claude-plugin/plugin.json" ]; then '
            '      PLUGIN_FLAGS="$PLUGIN_FLAGS --plugin-dir ${d%/}"; '
            "    fi; "
            "  done; "
            "fi; "
            f"exec {_quoted_args} $PLUGIN_FLAGS"
        )
        return ["sh", "-c", _plugin_scan]
