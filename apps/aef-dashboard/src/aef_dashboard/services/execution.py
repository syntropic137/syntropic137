"""Workflow execution service.

This service orchestrates workflow execution using the WorkflowExecutionEngine
from aef_domain. It handles:
- Wiring up dependencies (repositories, workspace service, agent factory)
- Tracking execution status for the Dashboard UI
- Running executions in background tasks

Real-time UI updates flow through the event store:
  Event Store → Subscription Service → RealTimeProjection → WebSocket

This follows proper event sourcing patterns - all events flow through the
event store, and the UI is updated via projections.

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
│  Event Store → Subscription Service → RealTimeProjection → WebSocket        │
└─────────────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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

logger = get_logger(__name__)


class ExecutionService:
    """Orchestrates workflow execution via WorkflowExecutionEngine.

    This service is a thin wrapper that:
    1. Wires up dependencies from aef_adapters
    2. Calls WorkflowExecutionEngine.execute()
    3. Updates the in-memory tracker for Dashboard status polling

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
        execution_tracker: dict[str, dict] | None = None,
    ) -> None:
        """Run a workflow execution.

        This method runs in a background task and updates the tracker
        as execution progresses.

        Args:
            execution_id: Unique ID for this execution.
            workflow_id: The workflow to execute.
            inputs: Input variables for the workflow.
            provider: Agent provider to use (default: claude).
            max_budget_usd: Optional budget cap (not yet implemented).
            execution_tracker: Dict to update with execution status.
        """
        # TODO: Replace in-memory tracker with WorkflowExecutionDetailProjection query
        # The proper pattern is: Event Store → Subscription → Projection → API query
        # This in-memory dict is a temporary workaround for real-time status during execution
        tracker = execution_tracker or {}

        try:
            # Initialize tracker
            tracker[execution_id] = {
                "status": "starting",
                "started_at": datetime.now(UTC),
                "workflow_id": workflow_id,
                "provider": provider,
            }

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

            # Update tracker to running
            tracker[execution_id]["status"] = "running"

            # Execute workflow - engine handles everything:
            # - Loading workflow definition
            # - Creating workspace/container
            # - Running phases with Claude CLI
            # - Persisting events via aggregates
            # - Creating artifacts
            result: WorkflowExecutionResult = await engine.execute(
                workflow_id=workflow_id,
                inputs=inputs,
                execution_id=execution_id,
                use_container=True,  # Run in isolated Docker container
            )

            # Update tracker with result
            tracker[execution_id].update(
                {
                    "status": "completed" if result.is_success else "failed",
                    "completed_at": result.completed_at or datetime.now(UTC),
                    "total_phases": result.metrics.total_phases,
                    "completed_phases": result.metrics.completed_phases,
                    "total_tokens": result.metrics.total_tokens,
                    "total_cost_usd": float(result.metrics.total_cost_usd),
                    "artifact_ids": result.artifact_ids,
                    "error": result.error_message,
                }
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

        except Exception as e:
            logger.exception("Workflow execution failed unexpectedly")
            tracker[execution_id] = {
                **tracker.get(execution_id, {}),
                "status": "failed",
                "error": str(e),
                "completed_at": datetime.now(UTC),
            }
