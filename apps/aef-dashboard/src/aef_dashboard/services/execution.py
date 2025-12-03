"""Workflow execution service.

This service orchestrates workflow execution using the AgenticWorkflowExecutor.
It bridges execution events to the SSE stream and persists artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentic_logging import get_logger

from aef_dashboard.api.events import push_event

logger = get_logger(__name__)


# =============================================================================
# Workflow Definition Adapter
# =============================================================================


@dataclass
class PhaseDefinitionAdapter:
    """Adapts stored phase to WorkflowPhase protocol."""

    phase_id: str
    name: str
    order: int
    description: str | None = None
    prompt_template: str = "Complete the task for phase: {{phase_id}}"
    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    output_artifact_type: str = "text"
    timeout_seconds: int = 300


@dataclass
class WorkflowDefinitionAdapter:
    """Adapts stored workflow to WorkflowDefinition protocol."""

    workflow_id: str
    name: str
    phases: list[PhaseDefinitionAdapter]


# =============================================================================
# Execution Service
# =============================================================================


class ExecutionService:
    """Orchestrates workflow execution and event streaming.

    This service:
    1. Loads workflow definitions from the repository
    2. Creates an AgenticWorkflowExecutor with appropriate factories
    3. Runs the execution and yields events
    4. Bridges events to the SSE stream
    5. Persists artifacts on phase completion
    """

    def __init__(self) -> None:
        """Initialize the execution service."""
        from aef_adapters.projections import get_projection_manager

        self._base_workspace_path = Path.cwd() / ".aef-workspaces"
        self._projection_manager = get_projection_manager()

    async def run_workflow(
        self,
        execution_id: str,
        workflow_id: str,
        inputs: dict[str, str],
        provider: str = "claude",
        max_budget_usd: float | None = None,
        execution_tracker: dict[str, dict] | None = None,
    ) -> None:
        """Run a workflow execution.

        This method runs in a background task and streams events
        to the SSE endpoint as execution progresses.

        Args:
            execution_id: Unique ID for this execution.
            workflow_id: The workflow to execute.
            inputs: Input variables for the workflow.
            provider: Agent provider to use.
            max_budget_usd: Optional budget cap.
            execution_tracker: Dict to update with execution status.
        """
        tracker = execution_tracker or {}

        try:
            # Update tracker
            tracker[execution_id] = {
                **tracker.get(execution_id, {}),
                "status": "loading",
                "started_at": datetime.now(UTC),
            }

            # Load workflow definition
            workflow_def = await self._load_workflow_definition(workflow_id)
            if workflow_def is None:
                raise ValueError(f"Workflow {workflow_id} not found")

            tracker[execution_id]["total_phases"] = len(workflow_def.phases)
            tracker[execution_id]["status"] = "running"

            # Try to import agentic components
            try:
                from aef_adapters.orchestration import AgenticWorkflowExecutor
                from aef_adapters.orchestration.executor import (
                    PhaseCompleted,
                    PhaseFailed,
                    PhaseStarted,
                    WorkflowCompleted,
                    WorkflowFailed,
                    WorkflowStarted,
                )
                from aef_adapters.orchestration.factory import (
                    get_agentic_agent,
                    get_workspace,
                )

                # Create executor
                executor = AgenticWorkflowExecutor(
                    agent_factory=get_agentic_agent,
                    workspace_factory=get_workspace,
                    base_workspace_path=self._base_workspace_path,
                    default_provider=provider,
                    default_max_budget_usd=max_budget_usd,
                )

                # Execute and stream events
                async for event in executor.execute(
                    workflow_def,
                    inputs,
                    execution_id=execution_id,
                    provider=provider,
                ):
                    # Bridge to SSE
                    self._bridge_event_to_sse(event)

                    # Update tracker
                    if isinstance(event, WorkflowStarted):
                        tracker[execution_id]["status"] = "running"

                    elif isinstance(event, PhaseStarted):
                        tracker[execution_id]["current_phase"] = event.phase_id

                    elif isinstance(event, PhaseCompleted):
                        tracker[execution_id]["completed_phases"] = (
                            tracker[execution_id].get("completed_phases", 0) + 1
                        )
                        tracker[execution_id]["current_phase"] = None
                        # Persist artifact
                        await self._persist_artifact(event)

                    elif isinstance(event, PhaseFailed):
                        tracker[execution_id]["status"] = "failed"
                        tracker[execution_id]["error"] = event.error

                    elif isinstance(event, WorkflowCompleted):
                        tracker[execution_id]["status"] = "completed"
                        tracker[execution_id]["completed_at"] = datetime.now(UTC)

                    elif isinstance(event, WorkflowFailed):
                        tracker[execution_id]["status"] = "failed"
                        tracker[execution_id]["error"] = event.error
                        tracker[execution_id]["completed_at"] = datetime.now(UTC)

            except ImportError as e:
                logger.warning(f"Agentic components not available, using simulated execution: {e}")
                # Fall back to simulated execution for demo/testing
                await self._run_simulated_execution(execution_id, workflow_def, inputs, tracker)

        except Exception as e:
            logger.exception("Workflow execution failed")
            tracker[execution_id] = {
                **tracker.get(execution_id, {}),
                "status": "failed",
                "error": str(e),
                "completed_at": datetime.now(UTC),
            }

            # Push failure event
            push_event(
                "workflow_failed",
                {
                    "workflow_id": workflow_id,
                    "execution_id": execution_id,
                    "error": str(e),
                },
            )

    async def _load_workflow_definition(self, workflow_id: str) -> WorkflowDefinitionAdapter | None:
        """Load workflow definition from repository.

        Args:
            workflow_id: The workflow ID to load.

        Returns:
            WorkflowDefinitionAdapter or None if not found.
        """
        from aef_adapters.projections import get_projection_manager
        from aef_domain.contexts.workflows.domain.queries import GetWorkflowDetailQuery
        from aef_domain.contexts.workflows.slices.get_workflow_detail import (
            GetWorkflowDetailHandler,
        )

        manager = get_projection_manager()
        handler = GetWorkflowDetailHandler(manager.workflow_detail)

        query = GetWorkflowDetailQuery(workflow_id=workflow_id)
        detail = await handler.handle(query)

        if detail is None:
            return None

        # Convert to adapter format
        phases = []
        for i, p in enumerate(detail.phases, 1):
            if isinstance(p, dict):
                phase_id = p.get("id", p.get("phase_id", f"phase-{i}"))
                name = p.get("name", f"Phase {i}")
                desc = p.get("description")
                prompt = p.get("prompt_template", f"Complete the {name} phase. {{{{topic}}}}")
            else:
                phase_id = getattr(p, "phase_id", f"phase-{i}")
                name = getattr(p, "name", f"Phase {i}")
                desc = getattr(p, "description", None)
                prompt = getattr(p, "prompt_template", f"Complete the {name} phase. {{{{topic}}}}")

            phases.append(
                PhaseDefinitionAdapter(
                    phase_id=phase_id,
                    name=name,
                    order=i,
                    description=desc,
                    prompt_template=prompt,
                    allowed_tools=frozenset({"Read", "Write", "Bash"}),
                    output_artifact_type="text",
                    timeout_seconds=300,
                )
            )

        return WorkflowDefinitionAdapter(
            workflow_id=detail.id,
            name=detail.name,
            phases=phases,
        )

    def _bridge_event_to_sse(self, event: Any) -> None:
        """Bridge an executor event to SSE.

        Args:
            event: The execution event to bridge.
        """
        # Import event types for matching
        try:
            from aef_adapters.orchestration.executor import (
                PhaseCompleted,
                PhaseFailed,
                PhaseStarted,
                WorkflowCompleted,
                WorkflowFailed,
                WorkflowStarted,
            )

            if isinstance(event, WorkflowStarted):
                push_event(
                    "workflow_started",
                    {
                        "workflow_id": event.workflow_id,
                        "execution_id": event.execution_id,
                        "workflow_name": event.workflow_name,
                        "total_phases": event.total_phases,
                    },
                )

            elif isinstance(event, PhaseStarted):
                push_event(
                    "phase_started",
                    {
                        "workflow_id": event.workflow_id,
                        "execution_id": event.execution_id,
                        "phase_id": event.phase_id,
                        "phase_name": event.phase_name,
                        "phase_order": event.phase_order,
                    },
                )

            elif isinstance(event, PhaseCompleted):
                push_event(
                    "phase_completed",
                    {
                        "workflow_id": event.workflow_id,
                        "execution_id": event.execution_id,
                        "phase_id": event.phase_id,
                        "artifact_bundle_id": event.artifact_bundle_id,
                        "tokens": event.total_tokens,
                        "duration_ms": event.duration_ms,
                    },
                )

            elif isinstance(event, PhaseFailed):
                push_event(
                    "phase_failed",
                    {
                        "workflow_id": event.workflow_id,
                        "execution_id": event.execution_id,
                        "phase_id": event.phase_id,
                        "error": event.error,
                    },
                )

            elif isinstance(event, WorkflowCompleted):
                push_event(
                    "workflow_completed",
                    {
                        "workflow_id": event.workflow_id,
                        "execution_id": event.execution_id,
                        "total_phases": event.total_phases,
                        "completed_phases": event.completed_phases,
                        "total_tokens": event.total_tokens,
                        "duration_ms": event.total_duration_ms,
                    },
                )

            elif isinstance(event, WorkflowFailed):
                push_event(
                    "workflow_failed",
                    {
                        "workflow_id": event.workflow_id,
                        "execution_id": event.execution_id,
                        "error": event.error,
                        "failed_phase_id": event.failed_phase_id,
                    },
                )

        except ImportError:
            # If imports fail, try to extract basic info
            event_type = type(event).__name__.lower()
            push_event(event_type, {"data": str(event)})

    async def _persist_artifact(self, event: Any) -> None:
        """Persist artifact from phase completion event.

        Converts the ArtifactBundle to an ArtifactCreated event and
        dispatches it to the projection manager.

        Args:
            event: PhaseCompleted event containing artifact info.
        """
        # Extract bundle from event (if available)
        bundle = getattr(event, "artifact_bundle", None)
        workflow_id = getattr(event, "workflow_id", "")
        phase_id = getattr(event, "phase_id", "")
        artifact_bundle_id = getattr(event, "artifact_bundle_id", "")
        completed_at = getattr(event, "completed_at", datetime.now(UTC))

        if bundle is None:
            # No bundle attached - create minimal artifact record
            artifact_event = {
                "artifact_id": artifact_bundle_id,
                "workflow_id": workflow_id,
                "session_id": None,
                "phase_id": phase_id,
                "artifact_type": "bundle",
                "title": f"Phase {phase_id} Output",
                "created_at": completed_at.isoformat()
                if hasattr(completed_at, "isoformat")
                else str(completed_at),
            }
        else:
            # Full bundle available - extract rich metadata
            # Get primary artifact type from bundle
            primary_type = "bundle"
            for f in getattr(bundle, "files", []):
                metadata = getattr(f, "metadata", None)
                if metadata and getattr(metadata, "is_primary", False):
                    primary_type = getattr(metadata, "artifact_type", "bundle")
                    if hasattr(primary_type, "value"):
                        primary_type = primary_type.value
                    break

            # Calculate total size
            total_size = sum(len(getattr(f, "content", b"")) for f in getattr(bundle, "files", []))

            artifact_event = {
                "artifact_id": getattr(bundle, "bundle_id", artifact_bundle_id),
                "workflow_id": workflow_id,
                "session_id": None,
                "phase_id": phase_id,
                "artifact_type": primary_type,
                "title": getattr(bundle, "title", None) or f"Phase {phase_id} Output",
                "created_at": completed_at.isoformat()
                if hasattr(completed_at, "isoformat")
                else str(completed_at),
                # Extended fields
                "file_count": len(getattr(bundle, "files", [])),
                "size_bytes": total_size,
            }

        # Dispatch to projection manager
        try:
            await self._projection_manager.dispatch_event("ArtifactCreated", artifact_event)
            logger.info(
                "Persisted artifact to projections",
                extra={
                    "artifact_id": artifact_event["artifact_id"],
                    "workflow_id": workflow_id,
                    "phase_id": phase_id,
                    "artifact_type": artifact_event["artifact_type"],
                },
            )
        except Exception as e:
            logger.error(
                "Failed to persist artifact",
                extra={
                    "artifact_id": artifact_event.get("artifact_id"),
                    "error": str(e),
                },
            )

    async def _run_simulated_execution(
        self,
        execution_id: str,
        workflow_def: WorkflowDefinitionAdapter,
        inputs: dict[str, str],
        tracker: dict[str, dict],
    ) -> None:
        """Run a simulated execution for demo/testing.

        This is used when the agentic components are not available.
        """
        import asyncio

        # Emit workflow started
        push_event(
            "workflow_started",
            {
                "workflow_id": workflow_def.workflow_id,
                "execution_id": execution_id,
                "workflow_name": workflow_def.name,
                "total_phases": len(workflow_def.phases),
                "inputs": inputs,
                "simulated": True,
            },
        )

        tracker[execution_id]["status"] = "running"

        # Simulate each phase
        for phase in workflow_def.phases:
            # Phase started
            push_event(
                "phase_started",
                {
                    "workflow_id": workflow_def.workflow_id,
                    "execution_id": execution_id,
                    "phase_id": phase.phase_id,
                    "phase_name": phase.name,
                    "phase_order": phase.order,
                    "simulated": True,
                },
            )
            tracker[execution_id]["current_phase"] = phase.phase_id

            # Simulate work (1-3 seconds)
            await asyncio.sleep(1.5)

            # Create real artifact for this phase
            artifact_id = str(uuid4())
            completed_at = datetime.now(UTC)

            # Persist artifact to projections (creates real entry)
            artifact_event = {
                "artifact_id": artifact_id,
                "workflow_id": workflow_def.workflow_id,
                "session_id": None,
                "phase_id": phase.phase_id,
                "artifact_type": "markdown",
                "title": f"{phase.name} Output",
                "created_at": completed_at.isoformat(),
                "file_count": 1,
                "size_bytes": len(f"# {phase.name} Output\n\nSimulated output for demonstration."),
            }
            await self._projection_manager.dispatch_event("ArtifactCreated", artifact_event)

            # Phase completed SSE event
            push_event(
                "phase_completed",
                {
                    "workflow_id": workflow_def.workflow_id,
                    "execution_id": execution_id,
                    "phase_id": phase.phase_id,
                    "artifact_bundle_id": artifact_id,
                    "tokens": 1500,
                    "duration_ms": 1500,
                    "simulated": True,
                },
            )

            tracker[execution_id]["completed_phases"] = (
                tracker[execution_id].get("completed_phases", 0) + 1
            )
            tracker[execution_id]["current_phase"] = None

        # Workflow completed
        push_event(
            "workflow_completed",
            {
                "workflow_id": workflow_def.workflow_id,
                "execution_id": execution_id,
                "total_phases": len(workflow_def.phases),
                "completed_phases": len(workflow_def.phases),
                "total_tokens": len(workflow_def.phases) * 1500,
                "duration_ms": len(workflow_def.phases) * 1500,
                "simulated": True,
            },
        )

        tracker[execution_id]["status"] = "completed"
        tracker[execution_id]["completed_at"] = datetime.now(UTC)
