"""Workflow execution service.

This service orchestrates workflow execution using the AgenticWorkflowExecutor.
It emits domain events via aggregates and persists artifacts.

Real-time UI updates are handled by the RealTimeProjection, which receives
events from the subscription service and pushes them to WebSocket clients.
This follows proper event sourcing patterns - all events flow through the
event store, and the UI is updated via projections.

NOTE: This service requires the agentic components to be installed.
If imports fail at startup, that's a deployment configuration error.
For testing, use MockAgenticExecutor with APP_ENVIRONMENT=test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agentic_logging import get_logger

from aef_adapters.orchestration import (
    create_workflow_executor,
    get_agentic_agent,
)

if TYPE_CHECKING:
    from aef_adapters.control import ControlSignal
from aef_adapters.orchestration.executor import (
    ExecutionCancelled,
    ExecutionPaused,
    ExecutionResumed,
    PhaseCompleted,
    PhaseFailed,
    PhaseStarted,
    ToolUsed,
    WorkflowCompleted,
    WorkflowFailed,
    WorkflowStarted,
)

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

            # Create executor with control signal checker
            from aef_dashboard.services.control import get_signal_adapter

            signal_adapter = get_signal_adapter()

            async def check_signal(exec_id: str) -> ControlSignal | None:
                """Check for control signals (pause/resume/cancel)."""
                return await signal_adapter.get_signal(exec_id)

            from aef_adapters.workspace_backends.service import WorkspaceService

            workspace_service = WorkspaceService.create_docker()

            # Create unified executor with required observability (M8)
            # Factory automatically wires TimescaleObservability
            executor = create_workflow_executor(
                agent_factory=get_agentic_agent,
                workspace_service=workspace_service,
                default_provider=provider,
                default_max_budget_usd=max_budget_usd,
                control_signal_checker=check_signal,
            )

            # Execute and stream events
            async for event in executor.execute(
                workflow_def,  # type: ignore[arg-type]
                inputs,
                execution_id=execution_id,
                provider=provider,
            ):
                # Update tracker and emit domain events via aggregates
                # Real-time UI updates happen via RealTimeProjection which
                # receives events from the subscription service
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
                    session_id = await self._start_session(
                        workflow_id=event.workflow_id,
                        execution_id=execution_id,
                        phase_id=event.phase_id,
                        provider=provider,
                    )
                    # Emit PhaseStarted domain event (via aggregate → event store)
                    await self._start_phase(
                        execution_id=execution_id,
                        workflow_id=event.workflow_id,
                        phase_id=event.phase_id,
                        phase_name=event.phase_name,
                        phase_order=event.phase_order,
                        session_id=session_id,
                    )

                elif isinstance(event, PhaseCompleted):
                    tracker[execution_id]["completed_phases"] = (
                        tracker[execution_id].get("completed_phases", 0) + 1
                    )
                    tracker[execution_id]["current_phase"] = None
                    # Complete session (via aggregate → event store)
                    completed_session_id = self._phase_sessions.get(event.phase_id)
                    if not completed_session_id:
                        logger.warning(
                            f"Session ID not found for phase_id={event.phase_id} "
                            f"in execution_id={execution_id}. "
                            "This may indicate a data inconsistency."
                        )
                    if completed_session_id:
                        await self._complete_session(
                            session_id=completed_session_id,
                            phase_id=event.phase_id,
                            total_tokens=event.total_tokens,
                            success=True,
                        )
                    # Persist artifact (also via aggregate → event store)
                    artifact_id = await self._persist_artifact(event, completed_session_id)

                    # Emit PhaseCompleted domain event for workflow projection
                    await self._complete_phase(
                        execution_id=event.execution_id,
                        workflow_id=event.workflow_id,
                        phase_id=event.phase_id,
                        session_id=session_id,
                        artifact_id=artifact_id,
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                        total_tokens=event.total_tokens,
                        cost_usd=float(event.estimated_cost_usd or 0),
                        duration_seconds=event.duration_ms / 1000,
                    )

                elif isinstance(event, PhaseFailed):
                    tracker[execution_id]["status"] = "failed"
                    tracker[execution_id]["error"] = event.error
                    # Complete session as failed (via aggregate → event store)
                    session_id = self._phase_sessions.get(event.phase_id) or ""
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
                        total_cost_usd=float(event.estimated_cost_usd),
                        duration_seconds=event.total_duration_ms / 1000,
                        artifact_ids=event.artifact_ids,
                    )

                elif isinstance(event, ToolUsed):
                    # Record each tool completion as an operation on the session
                    session_id = self._phase_sessions.get(event.phase_id) or ""
                    if session_id:
                        await self._record_tool_operation(
                            session_id=session_id,
                            tool_name=event.tool_name,
                            tool_use_id=event.tool_use_id,
                            success=event.success,
                            tool_output=event.tool_output,
                            duration_ms=event.duration_ms,
                            error=event.error,
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

                elif isinstance(event, ExecutionPaused):
                    tracker[execution_id]["status"] = "paused"
                    # Emit ExecutionPaused domain event
                    await self._pause_workflow_execution(
                        execution_id=event.execution_id,
                        phase_id=event.phase_id,
                        reason=event.reason,
                    )

                elif isinstance(event, ExecutionResumed):
                    tracker[execution_id]["status"] = "running"
                    # Emit ExecutionResumed domain event
                    await self._resume_workflow_execution(
                        execution_id=event.execution_id,
                        phase_id=event.phase_id,
                    )

                elif isinstance(event, ExecutionCancelled):
                    tracker[execution_id]["status"] = "cancelled"
                    tracker[execution_id]["completed_at"] = datetime.now(UTC)
                    # Emit ExecutionCancelled domain event
                    await self._cancel_workflow_execution(
                        execution_id=event.execution_id,
                        phase_id=event.phase_id,
                        reason=event.reason,
                    )

        except Exception as e:
            logger.exception("Workflow execution failed")
            tracker[execution_id] = {
                **tracker.get(execution_id, {}),
                "status": "failed",
                "error": str(e),
                "completed_at": datetime.now(UTC),
            }
            # Note: WorkflowFailed domain event is emitted via aggregate in the
            # normal flow. This exception handler is for unexpected errors.
            # The RealTimeProjection will receive the event from the subscription
            # service and push it to connected WebSocket clients.

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
                phase_id = str(p.get("id", p.get("phase_id", f"phase-{i}")))
                name = str(p.get("name", f"Phase {i}"))
                desc = p.get("description")
                prompt = p.get("prompt_template", f"Complete the {name} phase. {{{{topic}}}}")
            else:
                # PhaseDetail has 'id' attribute, not 'phase_id'
                phase_id = str(getattr(p, "id", getattr(p, "phase_id", f"phase-{i}")))
                name = str(getattr(p, "name", f"Phase {i}"))
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

    async def _start_session(
        self,
        workflow_id: str,
        execution_id: str,
        phase_id: str,
        provider: str,
    ) -> str:
        """Start a session for a phase using the aggregate pattern.

        This properly creates a session via the AgentSessionAggregate,
        which emits SessionStartedEvent to the event store.
        The subscription service will update projections.

        Args:
            workflow_id: The workflow ID.
            execution_id: The workflow execution/run ID.
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
                execution_id=execution_id,
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
            # Real-time UI updates happen via RealTimeProjection which
            # receives SessionStartedEvent from the subscription service

        except Exception as e:
            logger.error("Failed to start session", extra={"error": str(e)})
            # Don't fail the workflow, just log the error

        return session_id

    async def _record_tool_operation(
        self,
        session_id: str,
        tool_name: str,
        tool_use_id: str | None,
        success: bool,
        tool_output: str | None = None,
        duration_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        """Record a tool completion operation on the session.

        .. deprecated:: 0.3.0
            Tool events now flow through the Collector service (ADR-018 Pattern 2).
            Use CollectorClient.send_tool_* methods instead. This method will be
            removed in v0.4.0. Tool data should be retrieved from ToolTimelineProjection.

        This creates an OperationRecordedEvent for each tool call,
        providing full observability including output and timing.

        Note: When Collector is configured, tool events are sent directly
        from the AgenticWorkflowExecutor. This method remains for backward
        compatibility with existing sessions that don't use Collector.

        Args:
            session_id: The session ID.
            tool_name: Name of the tool used.
            tool_use_id: Unique ID of the tool invocation.
            success: Whether the tool call succeeded.
            tool_output: Output from the tool (may be truncated).
            duration_ms: How long the tool took in milliseconds.
            error: Error message if the tool failed.
        """
        # TODO: Remove this method in v0.4.0 when all tool events go through Collector
        import warnings

        warnings.warn(
            "_record_tool_operation is deprecated. Tool events now flow through "
            "Collector → ToolTimelineProjection (ADR-018 Pattern 2).",
            DeprecationWarning,
            stacklevel=2,
        )
        from aef_adapters.storage.repositories import get_session_repository
        from aef_domain.contexts.sessions._shared.value_objects import OperationType
        from aef_domain.contexts.sessions.record_operation.RecordOperationCommand import (
            RecordOperationCommand,
        )

        try:
            repository = get_session_repository()

            # Load existing aggregate
            aggregate = await repository.get_by_id(session_id)
            if aggregate is None:
                logger.warning(
                    "Session not found for tool operation",
                    extra={"session_id": session_id, "tool_name": tool_name},
                )
                return

            # Convert duration from ms to seconds
            duration_seconds = duration_ms / 1000 if duration_ms else None

            # Record the tool completion operation
            operation_command = RecordOperationCommand(
                aggregate_id=session_id,
                operation_type=OperationType.TOOL_COMPLETED,
                duration_seconds=duration_seconds,
                success=success,
                # Tool details
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                tool_output=tool_output,
                # Error info in metadata if present
                metadata={"error": error} if error else None,
            )
            aggregate.record_operation(operation_command)

            # Persist to event store
            await repository.save(aggregate)

            logger.debug(
                "[TOOL] Recorded tool completion",
                extra={
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id,
                    "success": success,
                    "duration_ms": duration_ms,
                    "has_output": tool_output is not None,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to record tool operation",
                extra={"error": str(e), "session_id": session_id, "tool_name": tool_name},
            )
            # Don't fail execution, just log the error

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
        from aef_domain.contexts.sessions._shared.value_objects import OperationType
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
                    aggregate_id=session_id,
                    operation_type=OperationType.AGENT_REQUEST,
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
                aggregate_id=session_id,
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
            # Real-time UI updates happen via RealTimeProjection which
            # receives SessionCompletedEvent from the subscription service

        except Exception as e:
            logger.error("Failed to complete session", extra={"error": str(e)})

        # Clean up tracking
        self._phase_sessions.pop(phase_id, None)
        self._phase_start_times.pop(phase_id, None)

    async def _complete_phase(
        self,
        execution_id: str,
        workflow_id: str,
        phase_id: str,
        session_id: str | None,
        artifact_id: str | None,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost_usd: float,
        duration_seconds: float,
    ) -> None:
        """Complete a phase using the aggregate pattern.

        This emits PhaseCompletedEvent to the event store, which the
        workflow detail projection picks up to update phase metrics.

        Args:
            execution_id: The workflow execution ID.
            workflow_id: The workflow template ID.
            phase_id: The phase ID.
            session_id: The session ID for this phase.
            artifact_id: The artifact ID if one was created.
            input_tokens: Input tokens used.
            output_tokens: Output tokens used.
            total_tokens: Total tokens used.
            cost_usd: Cost in USD.
            duration_seconds: Duration of the phase.
        """
        from decimal import Decimal

        from aef_adapters.storage.repositories import get_workflow_execution_repository
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            CompletePhaseCommand,
        )

        try:
            repository = get_workflow_execution_repository()

            # Load existing aggregate
            aggregate = await repository.get_by_id(execution_id)
            if aggregate is None:
                logger.warning(
                    "Workflow execution not found for phase completion",
                    extra={"execution_id": execution_id, "phase_id": phase_id},
                )
                return

            # Complete the phase
            command = CompletePhaseCommand(
                execution_id=execution_id,
                workflow_id=workflow_id,
                phase_id=phase_id,
                session_id=session_id,
                artifact_id=artifact_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=Decimal(str(cost_usd)),
                duration_seconds=duration_seconds,
            )
            aggregate._handle_command(command)

            # Persist to event store
            await repository.save(aggregate)

            logger.info(
                "Completed phase via aggregate",
                extra={
                    "execution_id": execution_id,
                    "phase_id": phase_id,
                    "total_tokens": total_tokens,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to complete phase",
                extra={"execution_id": execution_id, "phase_id": phase_id, "error": str(e)},
            )

    async def _start_phase(
        self,
        execution_id: str,
        workflow_id: str,
        phase_id: str,
        phase_name: str,
        phase_order: int,
        session_id: str | None = None,
    ) -> None:
        """Start a phase using the aggregate pattern.

        This emits PhaseStartedEvent to the event store, which the
        RealTimeProjection picks up to push to WebSocket clients.

        Args:
            execution_id: The workflow execution ID.
            workflow_id: The workflow template ID.
            phase_id: The phase ID.
            phase_name: The phase name.
            phase_order: The phase order (1-indexed).
            session_id: Optional session ID for this phase.
        """
        from aef_adapters.storage.repositories import get_workflow_execution_repository
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            StartPhaseCommand,
        )

        try:
            repository = get_workflow_execution_repository()

            # Load existing aggregate
            aggregate = await repository.get_by_id(execution_id)
            if aggregate is None:
                logger.warning(
                    "Workflow execution not found for phase start",
                    extra={"execution_id": execution_id, "phase_id": phase_id},
                )
                return

            # Start the phase
            command = StartPhaseCommand(
                execution_id=execution_id,
                workflow_id=workflow_id,
                phase_id=phase_id,
                phase_name=phase_name,
                phase_order=phase_order,
                session_id=session_id,
            )
            aggregate._handle_command(command)

            # Persist to event store
            await repository.save(aggregate)

            logger.info(
                "Started phase via aggregate",
                extra={
                    "execution_id": execution_id,
                    "phase_id": phase_id,
                    "phase_order": phase_order,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to start phase",
                extra={"execution_id": execution_id, "phase_id": phase_id, "error": str(e)},
            )

    async def _persist_artifact(self, event: Any, session_id: str | None = None) -> str | None:
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

        Returns:
            The artifact ID if created, None otherwise.
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
        artifact_type = ArtifactType.RESEARCH_SUMMARY  # Default type

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
                                artifact_type = ArtifactType.RESEARCH_SUMMARY
                        break  # Found primary, stop searching

            # Use bundle title if available
            bundle_title = getattr(bundle, "title", None)
            if bundle_title:
                title = bundle_title

        # If no content from bundle, create placeholder
        if not content:
            content = f"# {title}\n\nArtifact content stored in filesystem.\nSee: .aef-workspaces/"

        artifact_id: str | None = None
        try:
            # Create aggregate and dispatch command
            artifact_id = artifact_bundle_id or str(uuid4())
            aggregate = ArtifactAggregate()
            command = CreateArtifactCommand(
                aggregate_id=artifact_id,
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
            # Real-time UI updates happen via RealTimeProjection which
            # receives ArtifactCreatedEvent from the subscription service

        except Exception as e:
            logger.error(
                "Failed to persist artifact",
                extra={
                    "artifact_id": artifact_bundle_id,
                    "error": str(e),
                },
            )

        return artifact_id

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
        error_type: str | None,
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

    async def _pause_workflow_execution(
        self,
        execution_id: str,
        phase_id: str,
        reason: str | None,
    ) -> None:
        """Pause workflow execution using the aggregate pattern.

        This loads the WorkflowExecutionAggregate and emits
        ExecutionPausedEvent to the event store.
        """
        from aef_adapters.storage.repositories import get_workflow_execution_repository
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            PauseExecutionCommand,
        )

        try:
            repository = get_workflow_execution_repository()
            aggregate = await repository.get_by_id(execution_id)

            if aggregate is None:
                logger.warning(
                    "Workflow execution not found for pause",
                    extra={"execution_id": execution_id},
                )
                return

            command = PauseExecutionCommand(
                execution_id=execution_id,
                phase_id=phase_id,
                reason=reason,
            )
            aggregate._handle_command(command)

            await repository.save(aggregate)

            logger.info(
                "Paused workflow execution via aggregate",
                extra={"execution_id": execution_id, "phase_id": phase_id},
            )

        except Exception as e:
            logger.error(
                "Failed to pause workflow execution",
                extra={"execution_id": execution_id, "error": str(e)},
            )

    async def _resume_workflow_execution(
        self,
        execution_id: str,
        phase_id: str,
    ) -> None:
        """Resume workflow execution using the aggregate pattern.

        This loads the WorkflowExecutionAggregate and emits
        ExecutionResumedEvent to the event store.
        """
        from aef_adapters.storage.repositories import get_workflow_execution_repository
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            ResumeExecutionCommand,
        )

        try:
            repository = get_workflow_execution_repository()
            aggregate = await repository.get_by_id(execution_id)

            if aggregate is None:
                logger.warning(
                    "Workflow execution not found for resume",
                    extra={"execution_id": execution_id},
                )
                return

            command = ResumeExecutionCommand(
                execution_id=execution_id,
                phase_id=phase_id,
            )
            aggregate._handle_command(command)

            await repository.save(aggregate)

            logger.info(
                "Resumed workflow execution via aggregate",
                extra={"execution_id": execution_id, "phase_id": phase_id},
            )

        except Exception as e:
            logger.error(
                "Failed to resume workflow execution",
                extra={"execution_id": execution_id, "error": str(e)},
            )

    async def _cancel_workflow_execution(
        self,
        execution_id: str,
        phase_id: str,
        reason: str | None,
    ) -> None:
        """Cancel workflow execution using the aggregate pattern.

        This loads the WorkflowExecutionAggregate and emits
        ExecutionCancelledEvent to the event store.
        """
        from aef_adapters.storage.repositories import get_workflow_execution_repository
        from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
            CancelExecutionCommand,
        )

        try:
            repository = get_workflow_execution_repository()
            aggregate = await repository.get_by_id(execution_id)

            if aggregate is None:
                logger.warning(
                    "Workflow execution not found for cancel",
                    extra={"execution_id": execution_id},
                )
                return

            command = CancelExecutionCommand(
                execution_id=execution_id,
                phase_id=phase_id,
                reason=reason,
            )
            aggregate._handle_command(command)

            await repository.save(aggregate)

            logger.info(
                "Cancelled workflow execution via aggregate",
                extra={"execution_id": execution_id, "phase_id": phase_id},
            )

        except Exception as e:
            logger.error(
                "Failed to cancel workflow execution",
                extra={"execution_id": execution_id, "error": str(e)},
            )
