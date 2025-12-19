"""Workflow execution service.

This service orchestrates workflow execution using the WorkflowExecutionEngine
from aef_domain. It handles:
- Wiring up dependencies (repositories, workspace service, agent factory)
- Delegating execution to WorkflowExecutionEngine
- Querying execution status from WorkflowExecutionDetailProjection

Real-time UI updates flow through the event store:
  Event Store → Subscription Service → RealTimeProjection → WebSocket

Status queries flow through the projection:
  Event Store → WorkflowExecutionDetailProjection → Dashboard API

Architecture (ADR-023, ADR-029):
┌─────────────────────────────────────────────────────────────────────────────┐
│  Dashboard API                                                               │
│       │                                                                      │
│       ▼                                                                      │
│  ExecutionService.run_workflow()                                             │
│       │                                                                      │
│       ▼                                                                      │
│  WorkflowExecutionEngine.execute()  ←── FROM aef_domain                     │
│       │                                                                      │
│       ├─> Persists events via WorkflowExecutionAggregate                    │
│       ├─> Creates container via WorkspaceService                             │
│       └─> Runs Claude CLI via workspace.stream()                            │
│                                                                              │
│  Event Store → Subscription → WorkflowExecutionDetailProjection             │
│                     │                                                        │
│                     └─> RealTimeProjection → WebSocket                       │
└─────────────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentic_logging import get_logger

# Agent factory
from aef_adapters.agents import AgentProvider, get_agent

# Adapter imports - repositories and services
from aef_adapters.storage.repositories import (
    get_artifact_repository,
    get_session_repository,
    get_workflow_execution_repository,
    get_workflow_repository,
)
from aef_adapters.workspace_backends.service import WorkspaceService

# Domain imports - WorkflowExecutionEngine handles everything
from aef_domain.contexts.workflows import (
    WorkflowExecutionEngine,
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from aef_domain.contexts.workflows.domain.read_models.workflow_execution_detail import (
        WorkflowExecutionDetail,
    )

logger = get_logger(__name__)


class ExecutionService:
    """Orchestrates workflow execution via WorkflowExecutionEngine.

    This service:
    1. Wires up dependencies from aef_adapters
    2. Calls WorkflowExecutionEngine.execute()
    3. Queries execution status from WorkflowExecutionDetailProjection

    All business logic, event persistence, and agent execution is handled
    by WorkflowExecutionEngine in aef_domain.
    """

    def __init__(self) -> None:
        """Initialize the execution service."""
        pass

    def _create_execution_engine(self) -> WorkflowExecutionEngine:
        """Create a WorkflowExecutionEngine with all required dependencies.

        This wires up:
        - Workflow repository (for loading workflow definitions)
        - Execution repository (for persisting execution events)
        - Workspace service (for isolated container execution)
        - Session repository (for agent session tracking)
        - Artifact repository (for storing phase outputs)
        - Agent factory (for creating instrumented agents)

        Returns:
            Configured WorkflowExecutionEngine ready for execution.
        """

        def agent_factory(provider: str) -> Any:
            """Create an instrumented agent for the given provider."""
            try:
                provider_enum = AgentProvider(provider.lower())
            except ValueError:
                provider_enum = AgentProvider.CLAUDE
            return get_agent(provider_enum)

        return WorkflowExecutionEngine(
            workflow_repository=get_workflow_repository(),
            execution_repository=get_workflow_execution_repository(),
            workspace_service=WorkspaceService.create_docker(),
            session_repository=get_session_repository(),
            artifact_repository=get_artifact_repository(),
            agent_factory=agent_factory,
        )

    async def run_workflow(
        self,
        execution_id: str,
        workflow_id: str,
        inputs: dict[str, str],
        provider: str = "claude",
        max_budget_usd: float | None = None,  # noqa: ARG002 - Reserved for future budget tracking
    ) -> WorkflowExecutionResult:
        """Run a workflow execution.

        This method executes the workflow and returns the result.
        Status is persisted via events → WorkflowExecutionDetailProjection.

        Args:
            execution_id: Unique ID for this execution.
            workflow_id: The workflow to execute.
            inputs: Input variables for the workflow.
            provider: Agent provider to use (default: claude).
            max_budget_usd: Optional budget cap (not yet implemented).

        Returns:
            WorkflowExecutionResult with execution outcome.
        """
        logger.info(
            "Starting workflow execution",
            extra={
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "provider": provider,
            },
        )

        # Create engine with all dependencies wired up
        engine = self._create_execution_engine()

        # Execute workflow - engine handles everything:
        # - Loading workflow definition
        # - Creating workspace/container
        # - Running phases with Claude CLI
        # - Persisting events via aggregates (→ projection updates)
        # - Creating artifacts
        result: WorkflowExecutionResult = await engine.execute(
            workflow_id=workflow_id,
            inputs=inputs,
            execution_id=execution_id,
            use_container=True,  # Run in isolated Docker container
        )

        if result.is_success:
            logger.info(
                "Workflow execution completed",
                extra={
                    "execution_id": execution_id,
                    "workflow_id": workflow_id,
                    "phases": result.metrics.completed_phases,
                    "tokens": result.metrics.total_tokens,
                },
            )
        else:
            logger.warning(
                "Workflow execution failed",
                extra={
                    "execution_id": execution_id,
                    "workflow_id": workflow_id,
                    "error": result.error_message,
                },
            )

        return result

    async def get_execution_status(self, execution_id: str) -> WorkflowExecutionDetail | None:
        """Get the current status of an execution from the projection.

        This queries the WorkflowExecutionDetailProjection which is updated
        in real-time as events flow through the event store.

        Args:
            execution_id: The execution ID.

        Returns:
            WorkflowExecutionDetail or None if not found.
        """
        from aef_adapters.projections import get_projection_manager

        manager = get_projection_manager()
        return await manager.workflow_execution_detail.get_by_id(execution_id)
