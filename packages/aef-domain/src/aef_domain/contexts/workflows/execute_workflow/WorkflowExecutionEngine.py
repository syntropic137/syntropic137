"""WorkflowExecutionEngine - orchestrates workflow execution across phases.

See ADR-023: Workspace-First Execution Model for architectural decisions.

Key requirements:
- WorkspaceRouter is REQUIRED - agents run inside isolated workspaces
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

from aef_domain.contexts.artifacts._shared.value_objects import ArtifactType
from aef_domain.contexts.workflows._shared.execution_value_objects import (
    ExecutablePhase,
    ExecutionMetrics,
    ExecutionStatus,
    PhaseResult,
    PhaseStatus,
)
from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
    CompleteExecutionCommand,
    CompletePhaseCommand,
    FailExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)

if TYPE_CHECKING:
    from aef_adapters.agents.instrumented import InstrumentedAgent
    from aef_adapters.workspaces.router import WorkspaceRouter
    from aef_adapters.workspaces.types import IsolatedWorkspaceConfig
    from aef_domain.contexts.artifacts._shared.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from aef_domain.contexts.artifacts.domain.services.artifact_query_service import (
        ArtifactQueryServiceProtocol,
    )
    from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from aef_domain.contexts.workflows._shared.WorkflowAggregate import (
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
    phase_results: list[PhaseResult] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    completed_phase_ids: list[str] = field(default_factory=list)  # For querying artifacts


class WorkflowExecutionEngine:
    """Orchestrates workflow execution across phases.

    IMPORTANT (ADR-023): This engine requires:
    - WorkspaceRouter: Agents run inside isolated workspaces
    - WorkflowExecutionRepository: Events persist via aggregate pattern

    Responsibilities:
    - Load workflow definition
    - Create isolated workspace for agent execution
    - Execute phases sequentially inside workspace
    - Manage phase input/output artifacts
    - Track execution metrics
    - Persist events via WorkflowExecutionAggregate

    Example:
        from aef_adapters.workspaces import get_workspace_router
        from aef_adapters.storage.repositories import get_workflow_execution_repository

        engine = WorkflowExecutionEngine(
            workflow_repository=workflow_repo,
            execution_repository=get_workflow_execution_repository(),
            workspace_router=get_workspace_router(),
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
        workspace_router: WorkspaceRouter,
        session_repository: SessionRepository,
        artifact_repository: ArtifactRepository,
        agent_factory: AgentFactory,
        artifact_query_service: ArtifactQueryServiceProtocol | None = None,
    ) -> None:
        """Initialize the workflow execution engine.

        Args:
            workflow_repository: Repository for Workflow aggregates
            execution_repository: Repository for WorkflowExecution aggregates (REQUIRED)
            workspace_router: Router for creating isolated workspaces (REQUIRED)
            session_repository: Repository for AgentSession aggregates
            artifact_repository: Repository for Artifact aggregates
            agent_factory: Factory for creating instrumented agents
            artifact_query_service: Service for querying artifacts (REQUIRED for
                multi-phase workflows). If None, phase outputs cannot be injected
                into subsequent phase prompts.

        Raises:
            ValueError: If execution_repository or workspace_router is None
        """
        if execution_repository is None:
            raise ValueError(
                "execution_repository is required per ADR-023. "
                "Use get_workflow_execution_repository() from aef_adapters.storage.repositories."
            )
        if workspace_router is None:
            raise ValueError(
                "workspace_router is required per ADR-023. "
                "Use get_workspace_router() from aef_adapters.workspaces."
            )

        self._workflows = workflow_repository
        self._executions = execution_repository
        self._router = workspace_router
        self._sessions = session_repository
        self._artifacts = artifact_repository
        self._agent_factory = agent_factory
        self._artifact_query = artifact_query_service

    async def execute(
        self,
        workflow_id: str,
        inputs: dict[str, Any],
        execution_id: str | None = None,
        _workspace_config: IsolatedWorkspaceConfig | None = None,
    ) -> WorkflowExecutionResult:
        """Execute a workflow from start to finish.

        Per ADR-023, agents execute inside isolated workspaces and all events
        are persisted via the WorkflowExecutionAggregate.

        Args:
            workflow_id: ID of the workflow to execute.
            inputs: Initial input variables for the workflow.
            execution_id: Optional custom execution ID.
            workspace_config: Optional workspace configuration override.

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
        ctx = ExecutionContext(
            workflow_id=workflow_id,
            execution_id=execution_id or str(uuid4()),
            started_at=datetime.now(UTC),
            inputs=inputs,
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
        # TODO: Each phase should create its own isolated workspace:
        #   1. Create workspace via self._router.create()
        #   2. Inject artifacts from previous phases
        #   3. Execute agent inside workspace (subprocess or SDK)
        #   4. Collect artifacts for next phase
        #   5. Destroy workspace (stateless)
        # For now, router is DI-enforced but agent runs in host process.
        # See ADR-023 and docs/PLAN-FULL-WORKSPACE-ISOLATION.md
        try:
            phases = self._get_executable_phases(workflow)
            for phase in sorted(phases, key=lambda p: p.order):
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
                    prompt_template=phase.prompt_template_id or "",
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
        """
        phase_started_at = datetime.now(UTC)
        session_id = str(uuid4())

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
        - Initial workflow inputs
        - Previous phase outputs (queried from DB via ArtifactQueryService)

        Note: Phase outputs are retrieved from the artifact projection, NOT from
        an in-memory dict. This ensures crash recovery and audit trail.
        """
        prompt = phase.prompt_template

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
        from aef_domain.contexts.artifacts.create_artifact.CreateArtifactCommand import (
            CreateArtifactCommand,
        )

        # Map string type to ArtifactType enum
        artifact_type_enum = self._map_artifact_type(artifact_type)

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
