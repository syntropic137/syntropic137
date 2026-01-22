"""WorkflowExecutionEngine - orchestrates workflow execution across phases.

See ADR-023: Workspace-First Execution Model for architectural decisions.

Key requirements:
- WorkspaceService is REQUIRED - agents run inside isolated workspaces
- WorkflowExecutionRepository is REQUIRED - events persist via aggregate
- All events flow through WorkflowExecutionAggregate for consistency
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

# ADR-029: Simplified Event System - use agentic_events from agentic-primitives
from agentic_events import enrich_event, parse_jsonl_line

# ADR-012: Workspace prompt for artifact output instructions
from agentic_workspace import AEF_WORKSPACE_PROMPT

from aef_domain.contexts.artifacts._shared.value_objects import ArtifactType
from aef_domain.contexts.observability.domain.events.agent_observation import (
    ObservationType,
)
from aef_domain.contexts.workflows._shared.ExecutionValueObjects import (
    ExecutablePhase,
    ExecutionMetrics,
    ExecutionStatus,
    PhaseResult,
    PhaseStatus,
)
from aef_domain.contexts.workflows.domain.WorkflowExecutionAggregate import (
    CompleteExecutionCommand,
    CompletePhaseCommand,
    FailExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)

if TYPE_CHECKING:
    from aef_adapters.agents.protocol import AgentProtocol as InstrumentedAgent  # Alias for compat
    from aef_adapters.conversations import ConversationStoragePort
    from aef_adapters.workspace_backends.service import WorkspaceService
    from aef_domain.contexts.artifacts._shared.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from aef_domain.contexts.artifacts.domain.ports.artifact_storage import (
        ArtifactContentStoragePort,
    )
    from aef_domain.contexts.artifacts.domain.services.artifact_query_service import (
        ArtifactQueryServiceProtocol,
    )
    from aef_domain.contexts.sessions.domain.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from aef_domain.contexts.workflows.domain.WorkflowAggregate import (
        WorkflowAggregate,
    )


logger = logging.getLogger(__name__)


class WorkflowRepository(Protocol):
    """Repository protocol for Workflow aggregates."""

    async def get_by_id(self, workflow_id: str) -> WorkflowAggregate | None:
        """Get a workflow by ID."""
        ...

    async def save(self, aggregate: WorkflowAggregate) -> None:
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
        from aef_adapters.workspace_backends.service import WorkspaceService
        from aef_adapters.storage.repositories import get_workflow_execution_repository

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
                "Use get_workflow_execution_repository() from aef_adapters.storage.repositories."
            )
        if workspace_service is None:
            raise ValueError(
                "workspace_service is required per ADR-023. "
                "Use WorkspaceService.create() from aef_adapters.workspace_backends.service."
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

    async def _record_observation(
        self,
        observation_type: ObservationType,
        session_id: str,
        data: dict[str, Any],
        execution_id: str | None = None,
        phase_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        """Record an agent observation to TimescaleDB.

        Args:
            observation_type: Type of observation (TOKEN_USAGE, TOOL_STARTED, TOOL_COMPLETED)
            session_id: The session ID
            data: Observation data (JSONB)
            execution_id: Optional execution ID
            phase_id: Optional phase ID
            workspace_id: Optional workspace ID
        """
        if self._observability_writer is None:
            return

        await self._observability_writer.record_observation(
            session_id=session_id,
            observation_type=observation_type.value,
            data=data,
            execution_id=execution_id,
            phase_id=phase_id,
            workspace_id=workspace_id,
        )

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

    def _get_executable_phases(self, workflow: WorkflowAggregate) -> list[ExecutablePhase]:
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
        _workflow: WorkflowAggregate,
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
        # Import session classes
        from aef_domain.contexts.sessions.domain.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions._shared.value_objects import OperationType
        from aef_domain.contexts.sessions.domain.commands.CompleteSessionCommand import (
            CompleteSessionCommand,
        )
        from aef_domain.contexts.sessions.domain.commands.RecordOperationCommand import (
            RecordOperationCommand,
        )
        from aef_domain.contexts.sessions.domain.commands.StartSessionCommand import (
            StartSessionCommand,
        )

        phase_started_at = datetime.now(UTC)
        session_id = str(uuid4())
        session: AgentSessionAggregate | None = None

        # Create and start session aggregate
        if self._sessions is not None:
            session = AgentSessionAggregate()
            start_session_cmd = StartSessionCommand(
                aggregate_id=session_id,
                workflow_id=ctx.workflow_id,
                execution_id=ctx.execution_id,
                phase_id=phase.phase_id,
                agent_provider=phase.agent_config.provider,
                agent_model=phase.agent_config.model,
            )
            session._handle_command(start_session_cmd)
            await self._sessions.save(session)
            logger.debug("Session started: %s (phase: %s)", session_id, phase.phase_id)

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
            from aef_adapters.agents import AgentConfig, AgentMessage, AgentRole

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
            await self._create_artifact(
                artifact_id=artifact_id,
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
                execution_id=ctx.execution_id,  # Link to execution run for retrieval
                session_id=session_id,
                artifact_type=phase.output_artifact_type,
                content=response.content,
                title=f"{phase.name} Output",
            )

            # Track completed phase for artifact queries (DB-backed, not in-memory)
            ctx.completed_phase_ids.append(phase.phase_id)
            ctx.artifact_ids.append(artifact_id)

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
            if session is not None and self._sessions is not None:
                # Record operation with tokens
                if response.input_tokens > 0 or response.output_tokens > 0:
                    record_op_cmd = RecordOperationCommand(
                        aggregate_id=session_id,
                        operation_type=OperationType.MESSAGE_RESPONSE,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        total_tokens=response.total_tokens,
                        success=True,
                        duration_seconds=duration,
                        metadata={"phase_id": phase.phase_id, "source": "direct_execution"},
                    )
                    session._handle_command(record_op_cmd)

                # Complete session
                complete_session_cmd = CompleteSessionCommand(
                    aggregate_id=session_id,
                    success=True,
                )
                session._handle_command(complete_session_cmd)
                await self._sessions.save(session)
                logger.debug(
                    "Session completed: %s (success, tokens: %d)", session_id, response.total_tokens
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
            if session is not None and self._sessions is not None:
                try:
                    complete_session_cmd = CompleteSessionCommand(
                        aggregate_id=session_id,
                        success=False,
                        error_message=str(e),
                    )
                    session._handle_command(complete_session_cmd)
                    await self._sessions.save(session)
                    logger.debug("Session completed: %s (failed: %s)", session_id, str(e))
                except Exception as session_err:
                    logger.warning("Failed to complete session %s: %s", session_id, session_err)

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

        # Substitute previous phase outputs from DB
        if self._artifact_query and ctx.completed_phase_ids:
            phase_outputs = await self._artifact_query.get_for_phase_injection(
                execution_id=ctx.execution_id,
                completed_phase_ids=ctx.completed_phase_ids,
            )
            for phase_id, content in phase_outputs.items():
                # Support both {{phase_id}} and {{phase_id_output}} patterns
                prompt = prompt.replace(f"{{{{{phase_id}}}}}", content)
                prompt = prompt.replace(f"{{{{{phase_id}_output}}}}", content)
        elif ctx.completed_phase_ids and not self._artifact_query:
            logger.warning(
                "artifact_query_service not configured - phase outputs cannot be "
                "injected into prompt for phase %s. Configure ArtifactQueryService "
                "for multi-phase workflows.",
                phase.phase_id,
            )

        return prompt

    async def _create_artifact(
        self,
        artifact_id: str,
        workflow_id: str,
        phase_id: str,
        execution_id: str,
        session_id: str,
        artifact_type: str,
        content: str,
        title: str,
    ) -> None:
        """Create and save an artifact.

        Two-tier storage (ADR-012):
        1. Content → Object storage (MinIO/S3) if configured
        2. Metadata + storage_uri → Event store

        Args:
            artifact_id: Unique artifact identifier
            workflow_id: Parent workflow ID
            phase_id: Phase that produced this artifact
            execution_id: Execution run ID (links to WorkflowExecution aggregate)
            session_id: Agent session ID
            artifact_type: Type of artifact (string, mapped to enum)
            content: Artifact content
            title: Human-readable title
        """
        from aef_domain.contexts.artifacts._shared.ArtifactAggregate import (
            ArtifactAggregate,
        )
        from aef_domain.contexts.artifacts.slices.create_artifact.CreateArtifactCommand import (
            CreateArtifactCommand,
        )

        # Map string type to ArtifactType enum
        artifact_type_enum = self._map_artifact_type(artifact_type)

        # Upload content to object storage if configured (ADR-012)
        storage_uri: str | None = None
        if self._artifact_content_storage is not None:
            try:
                result = await self._artifact_content_storage.upload(
                    artifact_id=artifact_id,
                    content=content.encode("utf-8"),
                    workflow_id=workflow_id,
                    phase_id=phase_id,
                    execution_id=execution_id,
                    content_type="text/markdown",
                    metadata={
                        "session_id": session_id,
                        "artifact_type": artifact_type,
                        "title": title,
                    },
                )
                storage_uri = result.storage_uri
                logger.info(
                    "Artifact content uploaded to object storage",
                    extra={
                        "artifact_id": artifact_id,
                        "storage_uri": storage_uri,
                        "size_bytes": result.size_bytes,
                    },
                )
            except Exception as e:
                # Log error but continue - content will still be in event store
                logger.warning(
                    "Failed to upload artifact to object storage, "
                    "content will be stored in event store only",
                    extra={"artifact_id": artifact_id, "error": str(e)},
                )

        aggregate = ArtifactAggregate()
        command = CreateArtifactCommand(
            aggregate_id=artifact_id,
            workflow_id=workflow_id,
            phase_id=phase_id,
            execution_id=execution_id,  # Links artifact to specific execution run
            session_id=session_id,
            artifact_type=artifact_type_enum,
            content=content,
            title=title,
            storage_uri=storage_uri,  # NEW: Reference to object storage
        )
        aggregate._handle_command(command)
        await self._artifacts.save(aggregate)

    def _map_artifact_type(self, type_str: str) -> ArtifactType:
        """Map string artifact type to enum."""
        type_mapping = {
            "text": ArtifactType.TEXT,
            "markdown": ArtifactType.MARKDOWN,
            "code": ArtifactType.CODE,
            "json": ArtifactType.JSON,
            "yaml": ArtifactType.YAML,
            "research_summary": ArtifactType.RESEARCH_SUMMARY,
            "plan": ArtifactType.PLAN,
            "execution_report": ArtifactType.EXECUTION_REPORT,
            "documentation": ArtifactType.DOCUMENTATION,
            "analysis_report": ArtifactType.ANALYSIS_REPORT,
            "requirements": ArtifactType.REQUIREMENTS,
            "design_doc": ArtifactType.DESIGN_DOC,
            "configuration": ArtifactType.CONFIGURATION,
            "script": ArtifactType.SCRIPT,
        }
        return type_mapping.get(type_str.lower(), ArtifactType.OTHER)

    async def _execute_phase_in_container(
        self,
        phase: ExecutablePhase,
        ctx: ExecutionContext,
        aggregate: WorkflowExecutionAggregate,
        tenant_id: str | None = None,
    ) -> PhaseResult:
        """Execute a phase inside an isolated container with sidecar proxy.

        This implements the full agent-in-container pattern per ADR-023:

        1. Create isolated workspace with sidecar via WorkspaceService
        2. Inject input artifacts from previous phases
        3. Write task.json with phase configuration
        4. Execute Claude CLI via workspace.stream() (ADR-029)
        5. Parse JSONL events and emit to aggregate
        6. Collect output artifacts
        7. Destroy workspace (stateless)

        Contract:
            This method RETURNS the PhaseResult - it does NOT append to ctx.
            The caller is responsible for:
            - ctx.phase_results.append(result)
            - ctx.completed_phase_ids.append(phase.phase_id)
            - ctx.artifact_ids.append(result.artifact_id) if applicable

            This follows the pattern: helper methods RETURN results, callers append.

        Args:
            phase: The phase to execute
            ctx: Execution context
            aggregate: Workflow execution aggregate for events
            tenant_id: Optional tenant ID for multi-tenancy

        Returns:
            PhaseResult with execution metrics

        Raises:
            WorkflowExecutionError: If phase execution fails
        """
        import json

        from aef_domain.contexts.sessions.domain.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions._shared.value_objects import OperationType
        from aef_domain.contexts.sessions.domain.commands.CompleteSessionCommand import (
            CompleteSessionCommand,
        )
        from aef_domain.contexts.sessions.domain.commands.RecordOperationCommand import (
            RecordOperationCommand,
        )
        from aef_domain.contexts.sessions.domain.commands.StartSessionCommand import (
            StartSessionCommand,
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
        # This tracks the session at a more granular level than the workflow aggregate
        session: AgentSessionAggregate | None = None
        if self._sessions is not None:
            session = AgentSessionAggregate()
            start_session_cmd = StartSessionCommand(
                aggregate_id=session_id,
                workflow_id=ctx.workflow_id,
                execution_id=ctx.execution_id,
                phase_id=phase.phase_id,
                agent_provider=phase.agent_config.provider,
                agent_model=phase.agent_config.model,
            )
            session._handle_command(start_session_cmd)
            await self._sessions.save(session)
            logger.debug("Session started: %s (phase: %s)", session_id, phase.phase_id)

        try:
            # Create isolated workspace using WorkspaceService
            # Setup phase secrets pattern (ADR-024): secrets available during
            # setup phase, cleared before agent runs
            async with self._workspace_service.create_workspace(
                execution_id=ctx.execution_id,
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
                with_sidecar=False,  # Sidecar not needed with setup phase pattern
                inject_tokens=False,  # Handled by setup phase
            ) as workspace:
                # Run setup phase with secrets (ADR-024)
                # Uses GitHub App to generate installation token if configured
                from aef_adapters.workspace_backends.service import SetupPhaseSecrets

                secrets = await SetupPhaseSecrets.create()

                setup_result = await workspace.run_setup_phase(secrets)
                if setup_result.exit_code != 0:
                    raise WorkflowExecutionError(
                        message=f"Setup phase failed: {setup_result.stderr}",
                        workflow_id=ctx.workflow_id,
                        phase_id=phase.phase_id,
                    )
                logger.info("Setup phase completed, secrets cleared")

                # Inject input artifacts from previous phases
                # ADR-036: Write to artifacts/input/ (not inputs/)
                if self._artifact_query and ctx.completed_phase_ids:
                    phase_outputs = await self._artifact_query.get_for_phase_injection(
                        execution_id=ctx.execution_id,
                        completed_phase_ids=ctx.completed_phase_ids,
                    )
                    # Write artifacts to /workspace/artifacts/input/
                    files_to_inject = [
                        (f"artifacts/input/{prev_phase_id}.md", content.encode())
                        for prev_phase_id, content in phase_outputs.items()
                    ]
                    if files_to_inject:
                        await workspace.inject_files(files_to_inject)

                # Build task.json (kept for future use with task file injection)
                prompt = await self._build_prompt(phase, ctx)
                _task_data = {
                    "phase": phase.phase_id,
                    "prompt": prompt,
                    "execution_id": ctx.execution_id,
                    "tenant_id": tenant_id or "default",
                    "inputs": ctx.inputs,
                    "artifacts": [f"{pid}.md" for pid in ctx.completed_phase_ids],
                    "config": {
                        "model": phase.agent_config.model,
                        "max_tokens": phase.agent_config.max_tokens,
                        "timeout_seconds": phase.timeout_seconds,
                    },
                }

                # ADR-029: Run Claude CLI directly (no aef-agent-runner wrapper)
                # Build the Claude CLI command
                # ADR-012: Append system prompt for artifact output instructions
                claude_cmd = [
                    "claude",
                    "--print",  # Non-interactive mode
                    "--verbose",  # Required for stream-json output format
                    "--append-system-prompt",
                    AEF_WORKSPACE_PROMPT,  # Workspace contract from agentic-primitives
                    prompt,
                    "--output-format",
                    "stream-json",  # Stream JSON for real-time events
                    "--dangerously-skip-permissions",  # Agent runs autonomously
                ]

                # Add allowed tools if specified
                if phase.agent_config.allowed_tools:
                    claude_cmd.extend(
                        [
                            "--allowedTools",
                            ",".join(phase.agent_config.allowed_tools),
                        ]
                    )

                # Execute Claude CLI and stream events
                # ANTHROPIC_API_KEY is passed to agent (needed for Claude calls)
                # GitHub auth uses cached credentials from setup phase (ADR-024)
                agent_env = {
                    "CLAUDE_SESSION_ID": session_id,  # For hook event correlation
                }
                if secrets.anthropic_api_key:
                    agent_env["ANTHROPIC_API_KEY"] = secrets.anthropic_api_key

                total_input_tokens = 0
                total_output_tokens = 0

                # Variables for observation events
                execution_id = ctx.execution_id
                workspace_id = getattr(workspace, "id", None)
                agent_model = phase.agent_config.model

                # Cache tool_use_id → tool_name for enriching tool_result events
                # Claude CLI's tool_result only has tool_use_id, not tool_name
                tool_names_cache: dict[str, str] = {}

                # ADR-037: Track active subagents (Task tool) for observability
                # tool_use_id → (agent_name, started_at, tools_used)
                active_subagents: dict[str, tuple[str, datetime, dict[str, int]]] = {}

                def _attribute_tool_to_latest_subagent(
                    tool: str, subagents: dict[str, tuple[str, datetime, dict[str, int]]]
                ) -> None:
                    """Attribute a tool call to the most recently started subagent."""
                    if not subagents or not tool:
                        return
                    latest_subagent_id = max(
                        subagents.keys(),
                        key=lambda k: subagents[k][1],  # Sort by started_at
                    )
                    _, _, tools_dict = subagents[latest_subagent_id]
                    tools_dict[tool] = tools_dict.get(tool, 0) + 1

                # ADR-035: Collect all JSONL lines for conversation storage
                conversation_lines: list[str] = []

                line_count = 0
                async for line in workspace.stream(
                    claude_cmd,
                    timeout_seconds=phase.timeout_seconds or 300,
                    environment=agent_env,
                ):
                    line_count += 1
                    logger.debug("Received line %d: %s", line_count, line[:100])

                    # ADR-035: Collect line for conversation storage
                    if line.strip():
                        conversation_lines.append(line)

                    # ADR-029: Try hook event first (from agentic_events)
                    hook_event = parse_jsonl_line(line)
                    if hook_event:
                        # Enrich with workflow context
                        enriched = enrich_event(
                            hook_event,
                            execution_id=execution_id,
                            phase_id=phase.phase_id,
                        )
                        logger.debug("Hook event: %s", enriched.get("event_type"))

                        # Store hook events directly via observability writer
                        if self._observability_writer is not None:
                            await self._record_observation(
                                observation_type=enriched.get("event_type", "unknown"),
                                session_id=session_id,
                                data=enriched.get("context", {}),
                                execution_id=execution_id,
                                phase_id=phase.phase_id,
                                workspace_id=workspace_id,
                            )

                        # ADR-037: Detect subagent lifecycle from Task tool events
                        hook_type = hook_event.get("type", "")
                        ctx_data = enriched.get("context", {})
                        tool_name = ctx_data.get("tool_name", "")
                        tool_use_id = ctx_data.get("tool_use_id", "")

                        if tool_name == "Task" and tool_use_id:
                            if hook_type == "tool_use_started":
                                # Parse agent_name from input_preview JSON
                                agent_name = "unknown"
                                input_preview = ctx_data.get("input_preview", "")
                                if input_preview:
                                    try:
                                        import json

                                        input_data = json.loads(input_preview)
                                        agent_name = str(
                                            input_data.get(
                                                "subagent_type",
                                                input_data.get("description", "unknown"),
                                            )
                                        )[:50]
                                    except (json.JSONDecodeError, TypeError):
                                        pass
                                active_subagents[tool_use_id] = (agent_name, datetime.now(UTC), {})

                                if self._observability_writer is not None:
                                    await self._record_observation(
                                        observation_type=ObservationType.SUBAGENT_STARTED,
                                        session_id=session_id,
                                        data={
                                            "agent_name": agent_name,
                                            "subagent_tool_use_id": tool_use_id,
                                        },
                                        execution_id=execution_id,
                                        phase_id=phase.phase_id,
                                        workspace_id=workspace_id,
                                    )
                                    logger.info(
                                        "Subagent started: %s (id=%s)",
                                        agent_name,
                                        tool_use_id,
                                    )

                            elif hook_type == "tool_use_completed":
                                if tool_use_id in active_subagents:
                                    agent_name, started_at, tools_used = active_subagents.pop(
                                        tool_use_id
                                    )
                                    duration_ms = int(
                                        (datetime.now(UTC) - started_at).total_seconds() * 1000
                                    )
                                    success = ctx_data.get("success", True)

                                    if self._observability_writer is not None:
                                        await self._record_observation(
                                            observation_type=ObservationType.SUBAGENT_STOPPED,
                                            session_id=session_id,
                                            data={
                                                "agent_name": agent_name,
                                                "subagent_tool_use_id": tool_use_id,
                                                "duration_ms": duration_ms,
                                                "success": success,
                                                "tools_used": tools_used,
                                            },
                                            execution_id=execution_id,
                                            phase_id=phase.phase_id,
                                            workspace_id=workspace_id,
                                        )
                                        logger.info(
                                            "Subagent stopped: %s (id=%s, duration=%dms, tools=%s)",
                                            agent_name,
                                            tool_use_id,
                                            duration_ms,
                                            tools_used,
                                        )
                                else:
                                    # Non-Task tool completed - attribute to active subagent
                                    _attribute_tool_to_latest_subagent(tool_name, active_subagents)

                        continue

                    # Fall back to Claude CLI native events
                    try:
                        cli_event = json.loads(line)
                        cli_type = cli_event.get("type", "")
                        logger.debug("CLI event type: %s", cli_type)

                        # Handle token usage from result messages
                        if cli_type == "result" and "usage" in cli_event:
                            usage = cli_event.get("usage", {})
                            input_tokens = usage.get("input_tokens", 0)
                            output_tokens = usage.get("output_tokens", 0)
                            cache_creation = usage.get("cache_creation_input_tokens", 0)
                            cache_read = usage.get("cache_read_input_tokens", 0)
                            total_input_tokens += input_tokens
                            total_output_tokens += output_tokens

                            if self._observability_writer is not None:
                                await self._record_observation(
                                    observation_type=ObservationType.TOKEN_USAGE,
                                    session_id=session_id,
                                    data={
                                        "input_tokens": input_tokens,
                                        "output_tokens": output_tokens,
                                        "cache_creation_tokens": cache_creation,
                                        "cache_read_tokens": cache_read,
                                        "model": agent_model,
                                    },
                                    execution_id=execution_id,
                                    phase_id=phase.phase_id,
                                    workspace_id=workspace_id,
                                )
                                logger.debug(
                                    "Token usage: %d in, %d out",
                                    input_tokens,
                                    output_tokens,
                                )

                        # Extract tool events from assistant messages
                        # Claude CLI emits tool_use in message.content
                        if cli_type == "assistant":
                            message = cli_event.get("message", {})
                            content = message.get("content", [])
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "tool_use":
                                    tool_name = item.get("name", "unknown")
                                    tool_use_id = item.get("id", "unknown")
                                    tool_input = item.get("input", {})

                                    # Cache tool_name for enriching tool_result events
                                    tool_names_cache[tool_use_id] = tool_name

                                    if self._observability_writer is not None:
                                        await self._record_observation(
                                            observation_type=ObservationType.TOOL_STARTED,
                                            session_id=session_id,
                                            data={
                                                "tool_name": tool_name,
                                                "tool_use_id": tool_use_id,
                                                "input_preview": json.dumps(tool_input)[:500],
                                            },
                                            execution_id=execution_id,
                                            phase_id=phase.phase_id,
                                            workspace_id=workspace_id,
                                        )
                                        logger.debug("Tool started: %s", tool_name)

                                    # ADR-037: Detect Task tool as subagent start (raw CLI format)
                                    if tool_name == "Task" and tool_use_id:
                                        agent_name = str(
                                            tool_input.get(
                                                "subagent_type",
                                                tool_input.get("description", "unknown"),
                                            )
                                        )[:50]
                                        active_subagents[tool_use_id] = (
                                            agent_name,
                                            datetime.now(UTC),
                                            {},  # tools_used dict
                                        )

                                        if self._observability_writer is not None:
                                            await self._record_observation(
                                                observation_type=ObservationType.SUBAGENT_STARTED,
                                                session_id=session_id,
                                                data={
                                                    "agent_name": agent_name,
                                                    "subagent_tool_use_id": tool_use_id,
                                                },
                                                execution_id=execution_id,
                                                phase_id=phase.phase_id,
                                                workspace_id=workspace_id,
                                            )
                                            logger.info(
                                                "Subagent started (CLI): %s (id=%s)",
                                                agent_name,
                                                tool_use_id,
                                            )

                        # Handle tool results from user messages
                        if cli_type == "user":
                            message = cli_event.get("message", {})
                            content = message.get("content", [])
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "tool_result":
                                    tool_use_id = item.get("tool_use_id", "unknown")
                                    is_error = item.get("is_error", False)
                                    # Extract tool output content
                                    tool_content = item.get("content", "")
                                    if isinstance(tool_content, list):
                                        # Content can be a list of content blocks
                                        tool_content = " ".join(
                                            str(c.get("text", c) if isinstance(c, dict) else c)
                                            for c in tool_content
                                        )
                                    output_preview = (
                                        str(tool_content)[:500] if tool_content else None
                                    )
                                    # Look up tool_name from cache
                                    tool_name = tool_names_cache.get(tool_use_id, "unknown")

                                    if self._observability_writer is not None:
                                        await self._record_observation(
                                            observation_type=ObservationType.TOOL_COMPLETED,
                                            session_id=session_id,
                                            data={
                                                "tool_name": tool_name,  # Now included!
                                                "tool_use_id": tool_use_id,
                                                "success": not is_error,
                                                "output_preview": output_preview,  # Show why it failed!
                                            },
                                            execution_id=execution_id,
                                            phase_id=phase.phase_id,
                                            workspace_id=workspace_id,
                                        )
                                        logger.debug(
                                            "Tool completed: %s (%s) success=%s",
                                            tool_use_id,
                                            tool_name,
                                            not is_error,
                                        )

                                    # ADR-037: Detect Task tool completion as subagent stop (raw CLI format)
                                    if tool_name == "Task" and tool_use_id in active_subagents:
                                        agent_name, started_at, tools_used = active_subagents.pop(
                                            tool_use_id
                                        )
                                        duration_ms = int(
                                            (datetime.now(UTC) - started_at).total_seconds() * 1000
                                        )

                                        if self._observability_writer is not None:
                                            await self._record_observation(
                                                observation_type=ObservationType.SUBAGENT_STOPPED,
                                                session_id=session_id,
                                                data={
                                                    "agent_name": agent_name,
                                                    "subagent_tool_use_id": tool_use_id,
                                                    "duration_ms": duration_ms,
                                                    "success": not is_error,
                                                    "tools_used": tools_used,
                                                },
                                                execution_id=execution_id,
                                                phase_id=phase.phase_id,
                                                workspace_id=workspace_id,
                                            )
                                            logger.info(
                                                "Subagent stopped (CLI): %s (id=%s, duration=%dms, tools=%s)",
                                                agent_name,
                                                tool_use_id,
                                                duration_ms,
                                                tools_used,
                                            )
                                    elif tool_name != "Task":
                                        # Attribute non-Task tool to the most recently started subagent
                                        _attribute_tool_to_latest_subagent(
                                            tool_name, active_subagents
                                        )

                        if cli_type in ("system",):
                            logger.debug("CLI message: %s", cli_type)

                    except json.JSONDecodeError:
                        # Not all lines are JSON (could be plain text output)
                        logger.debug("Non-JSON line: %s", line[:50])

                logger.info(
                    "Agent runner streaming complete: %d lines, %d input tokens, %d output tokens",
                    line_count,
                    total_input_tokens,
                    total_output_tokens,
                )

                # ADR-035: Store conversation log to MinIO/S3
                if self._conversation_storage is not None and conversation_lines:
                    try:
                        from aef_adapters.conversations import SessionContext

                        conv_context = SessionContext(
                            execution_id=ctx.execution_id,
                            phase_id=phase.phase_id,
                            workflow_id=ctx.workflow_id,
                            model=phase.agent_config.model,
                            event_count=len(conversation_lines),
                            tool_counts={},  # Tool counts tracked separately via observability events
                            total_input_tokens=total_input_tokens,
                            total_output_tokens=total_output_tokens,
                            started_at=phase_started_at,
                            completed_at=datetime.now(UTC),
                            success=True,
                        )
                        await self._conversation_storage.store_session(
                            session_id=session_id,
                            lines=conversation_lines,
                            context=conv_context,
                        )
                        logger.info(
                            "Conversation log stored: %s (%d lines)",
                            session_id,
                            len(conversation_lines),
                        )
                    except Exception as conv_err:
                        # Don't fail the phase if conversation storage fails
                        logger.warning(
                            "Failed to store conversation log for %s: %s",
                            session_id,
                            conv_err,
                        )

                # Collect output artifacts
                # ADR-036: Collect from artifacts/output/ (not artifacts/)
                artifacts = await workspace.collect_files(
                    patterns=["artifacts/output/**/*"],
                )

                # Create artifact records for each output
                artifact_ids: list[str] = []
                for artifact_path, artifact_content in artifacts:
                    artifact_id = str(uuid4())
                    await self._create_artifact(
                        artifact_id=artifact_id,
                        workflow_id=ctx.workflow_id,
                        phase_id=phase.phase_id,
                        execution_id=ctx.execution_id,
                        session_id=session_id,
                        artifact_type=phase.output_artifact_type,
                        content=artifact_content.decode("utf-8", errors="replace"),
                        title=f"{phase.name}: {artifact_path}",
                    )
                    artifact_ids.append(artifact_id)
                    ctx.artifact_ids.append(artifact_id)

            # Workspace destroyed here (context manager exit)

            # Record success
            phase_completed_at = datetime.now(UTC)
            duration = (phase_completed_at - phase_started_at).total_seconds()

            result = PhaseResult(
                phase_id=phase.phase_id,
                status=PhaseStatus.COMPLETED,
                started_at=phase_started_at,
                completed_at=phase_completed_at,
                artifact_id=artifact_ids[0] if artifact_ids else None,
                session_id=session_id,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                total_tokens=total_input_tokens + total_output_tokens,
                cost_usd=self._estimate_cost(total_input_tokens, total_output_tokens),
            )
            # NOTE: Do NOT append here - caller is responsible for appending
            # to ctx.phase_results, ctx.completed_phase_ids, and ctx.artifact_ids.
            # This follows the contract: helper methods RETURN results, callers append.

            # Emit phase completed
            complete_cmd = CompletePhaseCommand(
                execution_id=ctx.execution_id,
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
                session_id=session_id,
                artifact_id=artifact_ids[0] if artifact_ids else None,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                total_tokens=total_input_tokens + total_output_tokens,
                cost_usd=result.cost_usd,
                duration_seconds=duration,
            )
            aggregate._handle_command(complete_cmd)

            # Record token usage on session before completing
            # This ensures SessionCompleted event contains accumulated tokens
            if session is not None and self._sessions is not None:
                if total_input_tokens > 0 or total_output_tokens > 0:
                    record_op_cmd = RecordOperationCommand(
                        aggregate_id=session_id,
                        operation_type=OperationType.MESSAGE_RESPONSE,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        total_tokens=total_input_tokens + total_output_tokens,
                        success=True,
                        duration_seconds=duration,
                        metadata={"phase_id": phase.phase_id, "source": "container_execution"},
                    )
                    session._handle_command(record_op_cmd)

                # Complete session aggregate (success)
                complete_session_cmd = CompleteSessionCommand(
                    aggregate_id=session_id,
                    success=True,
                )
                session._handle_command(complete_session_cmd)
                await self._sessions.save(session)
                logger.debug(
                    "Session completed: %s (success, tokens: %d)",
                    session_id,
                    total_input_tokens + total_output_tokens,
                )

            logger.info(
                "Phase completed (container mode): %s (tokens: %d)",
                phase.phase_id,
                total_input_tokens + total_output_tokens,
            )

            return result

        except Exception as e:
            # Record failure
            phase_completed_at = datetime.now(UTC)
            result = PhaseResult(
                phase_id=phase.phase_id,
                status=PhaseStatus.FAILED,
                started_at=phase_started_at,
                completed_at=phase_completed_at,
                session_id=session_id,
                error_message=str(e),
            )
            ctx.phase_results.append(result)

            # Complete session aggregate (failure)
            if session is not None and self._sessions is not None:
                try:
                    complete_session_cmd = CompleteSessionCommand(
                        aggregate_id=session_id,
                        success=False,
                        error_message=str(e),
                    )
                    session._handle_command(complete_session_cmd)
                    await self._sessions.save(session)
                    logger.debug("Session completed: %s (failed: %s)", session_id, str(e))
                except Exception as session_err:
                    # Don't let session persistence failure hide the original error
                    logger.warning(
                        "Failed to complete session %s: %s",
                        session_id,
                        session_err,
                    )

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

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """Estimate cost based on token usage.

        Uses Claude Sonnet pricing as default.
        """
        # Claude Sonnet 4 pricing (per million tokens)
        input_price = Decimal("3.00") / Decimal("1000000")
        output_price = Decimal("15.00") / Decimal("1000000")

        return Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price
