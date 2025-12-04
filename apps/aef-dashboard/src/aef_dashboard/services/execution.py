"""Workflow execution service.

This service orchestrates workflow execution using the AgenticWorkflowExecutor.
It bridges execution events to the SSE stream and persists artifacts.

NOTE: This service requires the agentic components to be installed.
If imports fail at startup, that's a deployment configuration error.
For testing, use MockAgenticExecutor with APP_ENVIRONMENT=test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentic_logging import get_logger

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
        # Track session IDs per phase for session event correlation
        self._phase_sessions: dict[str, str] = {}  # phase_id -> session_id
        self._phase_start_times: dict[str, datetime] = {}  # phase_id -> start_time

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

            # Create executor - imports are at top level, fail fast if not available
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

                # Update tracker and emit domain events via aggregates
                if isinstance(event, WorkflowStarted):
                    tracker[execution_id]["status"] = "running"
                    # Emit WorkflowExecutionStarted domain event
                    await self._start_workflow_execution(
                        execution_id=event.execution_id,
                        workflow_id=event.workflow_id,
                        workflow_name=event.workflow_name,
                        total_phases=event.total_phases,
                        inputs=event.inputs,
                    )

                elif isinstance(event, PhaseStarted):
                    tracker[execution_id]["current_phase"] = event.phase_id
                    # Start a session for this phase (via aggregate → event store)
                    await self._start_session(
                        workflow_id=event.workflow_id,
                        phase_id=event.phase_id,
                        provider=provider,
                    )

                elif isinstance(event, PhaseCompleted):
                    tracker[execution_id]["completed_phases"] = (
                        tracker[execution_id].get("completed_phases", 0) + 1
                    )
                    tracker[execution_id]["current_phase"] = None
                    # Complete session (via aggregate → event store)
                    session_id = self._phase_sessions.get(event.phase_id)
                    if session_id:
                        await self._complete_session(
                            session_id=session_id,
                            phase_id=event.phase_id,
                            total_tokens=event.total_tokens,
                            success=True,
                        )
                    # Persist artifact (also via aggregate → event store)
                    await self._persist_artifact(event, session_id)

                elif isinstance(event, PhaseFailed):
                    tracker[execution_id]["status"] = "failed"
                    tracker[execution_id]["error"] = event.error
                    # Complete session as failed (via aggregate → event store)
                    session_id = self._phase_sessions.get(event.phase_id)
                    if session_id:
                        await self._complete_session(
                            session_id=session_id,
                            phase_id=event.phase_id,
                            total_tokens=0,
                            success=False,
                            error=event.error,
                        )

                elif isinstance(event, WorkflowCompleted):
                    tracker[execution_id]["status"] = "completed"
                    tracker[execution_id]["completed_at"] = datetime.now(UTC)
                    # Emit WorkflowCompleted domain event
                    await self._complete_workflow_execution(
                        execution_id=event.execution_id,
                        completed_phases=event.completed_phases,
                        total_phases=event.total_phases,
                        total_input_tokens=event.total_input_tokens,
                        total_output_tokens=event.total_output_tokens,
                        total_cost_usd=event.total_cost_usd,
                        duration_seconds=event.total_duration_ms / 1000,
                        artifact_ids=event.artifact_ids,
                    )

                elif isinstance(event, WorkflowFailed):
                    tracker[execution_id]["status"] = "failed"
                    tracker[execution_id]["error"] = event.error
                    tracker[execution_id]["completed_at"] = datetime.now(UTC)
                    # Emit WorkflowFailed domain event
                    await self._fail_workflow_execution(
                        execution_id=event.execution_id,
                        error=event.error,
                        error_type=event.error_type,
                        failed_phase_id=event.failed_phase_id,
                        completed_phases=event.completed_phases,
                        total_phases=event.total_phases,
                    )

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

        else:
            # Unknown event type - log for debugging
            logger.debug("Unknown event type: %s", type(event).__name__)

    async def _start_session(
        self,
        workflow_id: str,
        phase_id: str,
        provider: str,
    ) -> str:
        """Start a session for a phase using the aggregate pattern.

        This properly creates a session via the AgentSessionAggregate,
        which emits SessionStartedEvent to the event store.
        The subscription service will update projections.

        Args:
            workflow_id: The workflow ID.
            phase_id: The phase ID.
            provider: The agent provider (e.g., 'claude').

        Returns:
            The generated session_id.
        """
        from aef_adapters.storage.repositories import get_session_repository
        from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
            AgentSessionAggregate,
        )
        from aef_domain.contexts.sessions.start_session.StartSessionCommand import (
            StartSessionCommand,
        )

        session_id = str(uuid4())

        # Track session for this phase (for later completion)
        self._phase_sessions[phase_id] = session_id
        self._phase_start_times[phase_id] = datetime.now(UTC)

        try:
            # Create aggregate and dispatch command
            aggregate = AgentSessionAggregate()
            command = StartSessionCommand(
                aggregate_id=session_id,
                workflow_id=workflow_id,
                phase_id=phase_id,
                milestone_id=None,
                agent_provider=provider,
                agent_model="claude-sonnet-4-20250514" if provider == "claude" else None,
                metadata={},
            )
            aggregate._handle_command(command)

            # Persist to event store (events are saved)
            repository = get_session_repository()
            await repository.save(aggregate)

            logger.info(
                "Started session via aggregate",
                extra={
                    "session_id": session_id,
                    "workflow_id": workflow_id,
                    "phase_id": phase_id,
                },
            )

            # Also push to SSE for real-time UI updates
            push_event(
                "session_started",
                {
                    "session_id": session_id,
                    "workflow_id": workflow_id,
                    "phase_id": phase_id,
                    "agent_provider": provider,
                    "started_at": datetime.now(UTC).isoformat(),
                },
            )

        except Exception as e:
            logger.error("Failed to start session", extra={"error": str(e)})
            # Don't fail the workflow, just log the error

        return session_id

    async def _complete_session(
        self,
        session_id: str,
        phase_id: str,
        total_tokens: int,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Complete a session using the aggregate pattern.

        This properly completes the session via the AgentSessionAggregate,
        which emits SessionCompletedEvent to the event store.
        The subscription service will update projections.

        Args:
            session_id: The session ID.
            phase_id: The phase ID.
            total_tokens: Total tokens used.
            success: Whether the session succeeded.
            error: Error message if failed.
        """
        from aef_adapters.storage.repositories import get_session_repository
        from aef_domain.contexts.sessions.complete_session.CompleteSessionCommand import (
            CompleteSessionCommand,
        )
        from aef_domain.contexts.sessions.record_operation.RecordOperationCommand import (
            RecordOperationCommand,
        )

        try:
            repository = get_session_repository()

            # Load existing aggregate
            aggregate = await repository.get_by_id(session_id)
            if aggregate is None:
                logger.warning("Session not found for completion", extra={"session_id": session_id})
                return

            # Record the operation (token usage)
            if total_tokens > 0:
                input_tokens = int(total_tokens * 0.3)
                output_tokens = int(total_tokens * 0.7)

                operation_command = RecordOperationCommand(
                    session_id=session_id,
                    operation_type="agent_execution",
                    duration_seconds=None,  # Could calculate from phase start time
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    tool_name=None,
                    success=success,
                    metadata={},
                )
                aggregate._handle_command(operation_command)

            # Complete the session
            complete_command = CompleteSessionCommand(
                session_id=session_id,
                success=success,
                error_message=error,
            )
            aggregate._handle_command(complete_command)

            # Persist to event store
            await repository.save(aggregate)

            logger.info(
                "Completed session via aggregate",
                extra={
                    "session_id": session_id,
                    "success": success,
                    "total_tokens": total_tokens,
                },
            )

            # Also push to SSE for real-time UI updates
            push_event(
                "session_completed",
                {
                    "session_id": session_id,
                    "status": "completed" if success else "failed",
                    "total_tokens": total_tokens,
                    "error_message": error,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )

        except Exception as e:
            logger.error("Failed to complete session", extra={"error": str(e)})

        # Clean up tracking
        self._phase_sessions.pop(phase_id, None)
        self._phase_start_times.pop(phase_id, None)

    async def _persist_artifact(self, event: Any, session_id: str | None = None) -> None:
        """Persist artifact from phase completion using the aggregate pattern.

        This properly creates an artifact via the ArtifactAggregate,
        which emits ArtifactCreatedEvent to the event store.
        The subscription service will update projections.

        NOTE: For MVP, artifact content is stored in the event itself.
        For production with large artifacts, content should be stored in
        object storage (S3/Supabase) and only a reference stored in the event.
        See: docs/adrs/ADR-012-artifact-storage.md

        Args:
            event: PhaseCompleted event containing artifact info.
            session_id: Optional session ID that produced this artifact.
        """
        from aef_adapters.storage.repositories import get_artifact_repository
        from aef_domain.contexts.artifacts._shared.ArtifactAggregate import ArtifactAggregate
        from aef_domain.contexts.artifacts._shared.value_objects import ArtifactType
        from aef_domain.contexts.artifacts.create_artifact.CreateArtifactCommand import (
            CreateArtifactCommand,
        )

        # Extract info from event
        bundle = getattr(event, "artifact_bundle", None)
        workflow_id = getattr(event, "workflow_id", "")
        phase_id = getattr(event, "phase_id", "")
        artifact_bundle_id = getattr(event, "artifact_bundle_id", "")

        # Try to get primary file content from bundle
        content = ""
        title = f"Phase {phase_id} Output"
        artifact_type = ArtifactType.RESEARCH_NOTES  # Default type

        if bundle is not None:
            # Find primary file in bundle
            for f in getattr(bundle, "files", []):
                file_content = getattr(f, "content", None)
                metadata = getattr(f, "metadata", None)

                if file_content:
                    # Decode if bytes
                    if isinstance(file_content, bytes):
                        try:
                            content = file_content.decode("utf-8")
                        except UnicodeDecodeError:
                            content = f"[Binary content: {len(file_content)} bytes]"
                    else:
                        content = str(file_content)

                if metadata:
                    is_primary = getattr(metadata, "is_primary", False)
                    if is_primary:
                        title = getattr(f, "filename", title) or title
                        # Map artifact type
                        raw_type = getattr(metadata, "artifact_type", None)
                        if raw_type:
                            if hasattr(raw_type, "value"):
                                raw_type = raw_type.value
                            # Try to match to ArtifactType enum
                            try:
                                artifact_type = ArtifactType(raw_type)
                            except ValueError:
                                artifact_type = ArtifactType.RESEARCH_NOTES
                        break  # Found primary, stop searching

            # Use bundle title if available
            bundle_title = getattr(bundle, "title", None)
            if bundle_title:
                title = bundle_title

        # If no content from bundle, create placeholder
        if not content:
            content = f"# {title}\n\nArtifact content stored in filesystem.\nSee: .aef-workspaces/"

        try:
            # Create aggregate and dispatch command
            aggregate = ArtifactAggregate()
            command = CreateArtifactCommand(
                aggregate_id=artifact_bundle_id or str(uuid4()),
                workflow_id=workflow_id,
                phase_id=phase_id,
                session_id=session_id,
                artifact_type=artifact_type,
                content_type=None,  # Use default (markdown)
                content=content,
                title=title,
                is_primary_deliverable=True,
                derived_from=None,
                metadata={},
            )
            aggregate._handle_command(command)

            # Persist to event store
            repository = get_artifact_repository()
            await repository.save(aggregate)

            logger.info(
                "Persisted artifact via aggregate",
                extra={
                    "artifact_id": aggregate.id,
                    "workflow_id": workflow_id,
                    "phase_id": phase_id,
                    "content_size": len(content),
                },
            )

            # Also push to SSE for real-time UI updates
            push_event(
                "artifact_created",
                {
                    "artifact_id": str(aggregate.id),
                    "workflow_id": workflow_id,
                    "phase_id": phase_id,
                    "session_id": session_id,
                    "title": title,
                    "artifact_type": artifact_type.value,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to persist artifact",
                extra={
                    "artifact_id": artifact_bundle_id,
                    "error": str(e),
                },
            )

    async def _start_workflow_execution(
        self,
        execution_id: str,
        workflow_id: str,
        workflow_name: str,
        total_phases: int,
        inputs: dict[str, Any],
    ) -> None:
        """Start workflow execution using the aggregate pattern.

        This creates a WorkflowExecutionAggregate and emits
        WorkflowExecutionStartedEvent to the event store.
        The subscription service will update workflow projections.

        Args:
            execution_id: The unique execution ID (becomes aggregate ID).
            workflow_id: The workflow being executed.
            workflow_name: Human-readable workflow name.
            total_phases: Number of phases in the workflow.
            inputs: Input variables for the execution.
        """
        from aef_adapters.storage.repositories import get_workflow_execution_repository
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            StartExecutionCommand,
            WorkflowExecutionAggregate,
        )

        try:
            # Create aggregate and dispatch command
            aggregate = WorkflowExecutionAggregate()
            command = StartExecutionCommand(
                execution_id=execution_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                total_phases=total_phases,
                inputs=inputs,
            )
            aggregate._handle_command(command)

            # Persist to event store
            repository = get_workflow_execution_repository()
            await repository.save(aggregate)

            logger.info(
                "Started workflow execution via aggregate",
                extra={
                    "execution_id": execution_id,
                    "workflow_id": workflow_id,
                    "total_phases": total_phases,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to start workflow execution",
                extra={"execution_id": execution_id, "error": str(e)},
            )

    async def _complete_workflow_execution(
        self,
        execution_id: str,
        completed_phases: int,
        total_phases: int,
        total_input_tokens: int,
        total_output_tokens: int,
        total_cost_usd: float,
        duration_seconds: float,
        artifact_ids: list[str],
    ) -> None:
        """Complete workflow execution using the aggregate pattern.

        This loads the WorkflowExecutionAggregate and emits
        WorkflowCompletedEvent to the event store.
        The subscription service will update workflow projections.

        Args:
            execution_id: The execution ID.
            completed_phases: Number of phases completed.
            total_phases: Total number of phases.
            total_input_tokens: Total input tokens used.
            total_output_tokens: Total output tokens used.
            total_cost_usd: Total cost in USD.
            duration_seconds: Total duration in seconds.
            artifact_ids: IDs of artifacts produced.
        """
        from decimal import Decimal

        from aef_adapters.storage.repositories import get_workflow_execution_repository
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            CompleteExecutionCommand,
        )

        try:
            repository = get_workflow_execution_repository()
            aggregate = await repository.get_by_id(execution_id)

            if aggregate is None:
                logger.warning(
                    "Workflow execution not found for completion",
                    extra={"execution_id": execution_id},
                )
                return

            command = CompleteExecutionCommand(
                execution_id=execution_id,
                completed_phases=completed_phases,
                total_phases=total_phases,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                total_cost_usd=Decimal(str(total_cost_usd)),
                duration_seconds=duration_seconds,
                artifact_ids=artifact_ids,
            )
            aggregate._handle_command(command)

            await repository.save(aggregate)

            logger.info(
                "Completed workflow execution via aggregate",
                extra={
                    "execution_id": execution_id,
                    "completed_phases": completed_phases,
                    "total_tokens": total_input_tokens + total_output_tokens,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to complete workflow execution",
                extra={"execution_id": execution_id, "error": str(e)},
            )

    async def _fail_workflow_execution(
        self,
        execution_id: str,
        error: str,
        error_type: str,
        failed_phase_id: str | None,
        completed_phases: int,
        total_phases: int,
    ) -> None:
        """Fail workflow execution using the aggregate pattern.

        This loads the WorkflowExecutionAggregate and emits
        WorkflowFailedEvent to the event store.
        The subscription service will update workflow projections.

        Args:
            execution_id: The execution ID.
            error: Error message.
            error_type: Type of error.
            failed_phase_id: ID of the phase that failed.
            completed_phases: Number of phases completed before failure.
            total_phases: Total number of phases.
        """
        from aef_adapters.storage.repositories import get_workflow_execution_repository
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            FailExecutionCommand,
        )

        try:
            repository = get_workflow_execution_repository()
            aggregate = await repository.get_by_id(execution_id)

            if aggregate is None:
                logger.warning(
                    "Workflow execution not found for failure",
                    extra={"execution_id": execution_id},
                )
                return

            command = FailExecutionCommand(
                execution_id=execution_id,
                error=error,
                error_type=error_type,
                failed_phase_id=failed_phase_id,
                completed_phases=completed_phases,
                total_phases=total_phases,
            )
            aggregate._handle_command(command)

            await repository.save(aggregate)

            logger.info(
                "Failed workflow execution via aggregate",
                extra={
                    "execution_id": execution_id,
                    "error": error,
                    "failed_phase_id": failed_phase_id,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to record workflow execution failure",
                extra={"execution_id": execution_id, "error": str(e)},
            )
