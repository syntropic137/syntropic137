"""Unified WorkflowExecutor - single implementation for all consumers.

This executor replaces both AgenticWorkflowExecutor and WorkflowExecutionEngine
with a single, unified implementation that:

1. REQUIRES ObservabilityPort - no silent failures (Poka-Yoke)
2. Streams ExecutionEvent for real-time UI updates
3. Uses event sourcing for domain events (aggregate persistence)
4. Uses ObservabilityPort for high-volume telemetry (TimescaleDB)

Architecture:
    - ADR-027: Unified Workflow Executor Architecture
    - M8: Unified Executor Architecture (PROJECT-PLAN)

Usage:
    from aef_adapters.orchestration import create_workflow_executor

    # Factory handles DI wiring (recommended)
    executor = create_workflow_executor(
        agent_factory=get_agentic_agent,
        workspace_service=workspace_service,
    )

    async for event in executor.execute(workflow, inputs):
        match event:
            case WorkflowStarted():
                print(f"Started: {event.workflow_id}")
            case PhaseCompleted():
                print(f"Phase done: {event.phase_id}")
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agentic_observability import (
    ObservabilityPort,
    ObservationContext,
    ObservationType,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from aef_adapters.agents.agentic_protocol import AgenticProtocol
    from aef_adapters.control import ControlSignal
    from aef_adapters.workspace_backends.service import WorkspaceService

logger = logging.getLogger(__name__)

# Control signal polling interval (seconds)
CONTROL_SIGNAL_POLL_INTERVAL = 0.5


# ============================================================================
# Execution Events (re-exported for convenience)
# ============================================================================

# Import from existing executor for backwards compatibility
from aef_adapters.orchestration.executor import (  # noqa: E402
    ExecutionCancelled,
    ExecutionContext,
    ExecutionEvent,
    ExecutionPaused,
    ExecutionResumed,
    PhaseCompleted,
    PhaseFailed,
    PhaseStarted,
    ToolBlockedExecution,
    ToolStarted,
    ToolUsed,
    TurnUpdate,
    WorkflowCompleted,
    WorkflowDefinition,
    WorkflowFailed,
    WorkflowPhase,
    WorkflowStarted,
)

# ============================================================================
# Unified Workflow Executor
# ============================================================================


class WorkflowExecutor:
    """Unified workflow executor that REQUIRES observability.

    This is the single implementation for executing workflows. It:
    - REQUIRES ObservabilityPort in constructor (no silent failures)
    - Streams ExecutionEvent for real-time UI updates
    - Records all tool operations and token usage via ObservabilityPort
    - Supports workspace isolation via WorkspaceService

    Why observability is required:
        The AEF platform's core value proposition is observability.
        An executor without observability is a black box that provides
        no insight into agent behavior. By requiring ObservabilityPort:
        - We enforce consistent telemetry across all execution paths
        - We prevent configuration drift between CLI and Dashboard
        - We make it impossible to accidentally skip observability

    Example:
        from aef_adapters.orchestration import create_workflow_executor

        # Use factory (recommended - handles DI)
        executor = create_workflow_executor(
            agent_factory=get_agentic_agent,
            workspace_service=workspace_service,
        )

        async for event in executor.execute(workflow, inputs):
            print(event)
    """

    def __init__(
        self,
        *,
        observability: ObservabilityPort,
        agent_factory: Callable[[str], AgenticProtocol],
        workspace_service: WorkspaceService,
        default_provider: str = "claude",
        default_max_turns: int = 50,
        default_max_budget_usd: float | None = None,
        control_signal_checker: Callable[[str], Awaitable[ControlSignal | None]] | None = None,
    ) -> None:
        """Initialize the unified executor.

        Args:
            observability: ObservabilityPort for recording telemetry (REQUIRED).
                          Use get_observability() to get the production adapter.
            agent_factory: Factory for creating agentic agents.
            workspace_service: WorkspaceService for isolated workspaces.
            default_provider: Default agent provider (e.g., "claude").
            default_max_turns: Default max turns per phase.
            default_max_budget_usd: Optional budget limit per phase.
            control_signal_checker: Optional callback for pause/resume/cancel.

        Raises:
            TypeError: If observability is None or not an ObservabilityPort.
        """
        if observability is None:
            raise TypeError(
                "WorkflowExecutor requires observability parameter. "
                "Use create_workflow_executor() factory for automatic DI, "
                "or pass get_observability() for production, "
                "or NullObservability for tests (requires AEF_ENVIRONMENT='test')."
            )

        if not isinstance(observability, ObservabilityPort):
            raise TypeError(
                f"observability must implement ObservabilityPort, got {type(observability).__name__}"
            )

        self._observability = observability
        self._agent_factory = agent_factory
        self._workspace_service = workspace_service
        self._base_path = Path.cwd() / ".aef-workspaces"
        self._default_provider = default_provider
        self._default_max_turns = default_max_turns
        self._default_max_budget_usd = default_max_budget_usd
        self._check_signal = control_signal_checker

    async def execute(
        self,
        workflow: WorkflowDefinition,
        inputs: dict[str, Any],
        *,
        execution_id: str | None = None,
        provider: str | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[ExecutionEvent]:
        """Execute a workflow, yielding events as execution progresses.

        Args:
            workflow: The workflow definition to execute.
            inputs: Initial input variables.
            execution_id: Optional custom execution ID.
            provider: Optional agent provider override.
            session_id: Optional session ID for observability correlation.

        Yields:
            ExecutionEvent instances as execution progresses.
        """
        exec_id = execution_id or str(uuid4())
        sess_id = session_id or exec_id

        # Create observability context for this execution
        obs_context = ObservationContext(
            session_id=sess_id,
            execution_id=exec_id,
            workflow_id=workflow.workflow_id,
        )

        try:
            async for event in self._execute_workflow(
                workflow, inputs, exec_id, provider, obs_context
            ):
                yield event
        finally:
            # Ensure all observations are flushed
            await self._observability.flush()

    async def _execute_workflow(
        self,
        workflow: WorkflowDefinition,
        inputs: dict[str, Any],
        execution_id: str,
        provider: str | None,
        obs_context: ObservationContext,
    ) -> AsyncIterator[ExecutionEvent]:
        """Internal workflow execution logic."""
        # Import types from existing executor

        # Initialize context
        ctx = ExecutionContext(
            workflow_id=workflow.workflow_id,
            execution_id=execution_id,
            workflow_name=workflow.name,
            started_at=datetime.now(UTC),
            inputs=inputs,
        )

        # Record session started observation
        await self._observability.record(
            ObservationType.SESSION_STARTED,
            obs_context,
            {
                "workflow_name": workflow.name,
                "total_phases": len(workflow.phases),
                "inputs_keys": list(inputs.keys()),
            },
        )

        # Emit workflow started
        yield WorkflowStarted(
            workflow_id=ctx.workflow_id,
            execution_id=ctx.execution_id,
            workflow_name=ctx.workflow_name,
            total_phases=len(workflow.phases),
            started_at=ctx.started_at,
            inputs=inputs,
        )

        # Get agent
        agent = self._agent_factory(provider or self._default_provider)
        if not agent.is_available:
            await self._observability.record(
                ObservationType.SESSION_ERROR,
                obs_context,
                {"error": f"Agent provider '{provider or self._default_provider}' not available"},
            )
            yield WorkflowFailed(
                workflow_id=ctx.workflow_id,
                execution_id=ctx.execution_id,
                failed_at=datetime.now(UTC),
                failed_phase_id=None,
                error=f"Agent provider '{provider or self._default_provider}' is not available",
                error_type="AgentNotAvailable",
                completed_phases=0,
                total_phases=len(workflow.phases),
            )
            return

        # Execute phases sequentially
        sorted_phases = sorted(workflow.phases, key=lambda p: p.order)

        for phase in sorted_phases:
            phase_context = ObservationContext(
                session_id=obs_context.session_id,
                execution_id=execution_id,
                workflow_id=workflow.workflow_id,
                phase_id=phase.phase_id,
            )

            try:
                async for event in self._execute_phase(
                    agent,
                    phase,
                    ctx,
                    phase_context,
                ):
                    yield event

                    # Check for phase failure
                    if isinstance(event, PhaseFailed):
                        await self._observability.record(
                            ObservationType.SESSION_ERROR,
                            obs_context,
                            {"error": event.error, "failed_phase": phase.phase_id},
                        )
                        yield WorkflowFailed(
                            workflow_id=ctx.workflow_id,
                            execution_id=ctx.execution_id,
                            failed_at=datetime.now(UTC),
                            failed_phase_id=phase.phase_id,
                            error=event.error,
                            error_type=event.error_type,
                            completed_phases=len(
                                [r for r in ctx.phase_results if isinstance(r, PhaseCompleted)]
                            ),
                            total_phases=len(workflow.phases),
                        )
                        return

            except Exception as e:
                logger.exception(f"Phase {phase.phase_id} failed with exception")
                await self._observability.record(
                    ObservationType.SESSION_ERROR,
                    obs_context,
                    {
                        "error": str(e),
                        "failed_phase": phase.phase_id,
                        "error_type": type(e).__name__,
                    },
                )
                yield PhaseFailed(
                    workflow_id=ctx.workflow_id,
                    execution_id=ctx.execution_id,
                    phase_id=phase.phase_id,
                    failed_at=datetime.now(UTC),
                    error=str(e),
                    error_type=type(e).__name__,
                )
                yield WorkflowFailed(
                    workflow_id=ctx.workflow_id,
                    execution_id=ctx.execution_id,
                    failed_at=datetime.now(UTC),
                    failed_phase_id=phase.phase_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    completed_phases=len(
                        [r for r in ctx.phase_results if isinstance(r, PhaseCompleted)]
                    ),
                    total_phases=len(workflow.phases),
                )
                return

        # All phases completed
        await self._observability.record(
            ObservationType.SESSION_COMPLETED,
            obs_context,
            {
                "total_phases": len(workflow.phases),
                "completed_phases": len(ctx.phase_results),
                "total_tokens": ctx.total_input_tokens + ctx.total_output_tokens,
            },
        )

        yield WorkflowCompleted(
            workflow_id=ctx.workflow_id,
            execution_id=ctx.execution_id,
            completed_at=datetime.now(UTC),
            total_phases=len(workflow.phases),
            completed_phases=len(ctx.phase_results),
            artifact_ids=[b.bundle_id for b in ctx.artifact_bundles],
            total_input_tokens=ctx.total_input_tokens,
            total_output_tokens=ctx.total_output_tokens,
            total_tokens=ctx.total_input_tokens + ctx.total_output_tokens,
            total_duration_ms=ctx.total_duration_ms,
            # Use accumulated SDK cost (includes tool token costs)
            estimated_cost_usd=ctx.total_cost_usd,
        )

    async def _execute_phase(
        self,
        agent: Any,  # AgenticProtocol
        phase: WorkflowPhase,
        ctx: ExecutionContext,
        obs_context: ObservationContext,
    ) -> AsyncIterator[ExecutionEvent]:
        """Execute a single phase with full observability.

        Uses WorkspaceService for proper Docker isolation with GitHub credentials.
        """
        # Import types here to avoid circular imports AND enable mypy type narrowing
        from aef_adapters.agents.agentic_types import (
            AgentExecutionConfig,
            TaskCompleted,
            TaskFailed,
            ToolBlocked,
            ToolUseCompleted,
            ToolUseStarted,
            TurnCompleted,
            Workspace,
            WorkspaceConfig,
        )
        from aef_adapters.artifacts import ArtifactBundle, PhaseContext

        phase_started_at = datetime.now(UTC)

        # Build task prompt first (needed for phase context)
        task = self._build_task(phase, ctx)

        # Create phase context with previous artifacts
        phase_context_obj = PhaseContext(
            task=task,
            phase_id=phase.phase_id,
            workflow_id=ctx.workflow_id,
            artifacts=ctx.artifact_bundles,
        )

        # Use WorkspaceService for Docker isolation (ADR-024: Setup Phase Secrets)
        # This creates an isolated container with GitHub credentials pre-configured
        async with self._workspace_service.create_workspace(
            execution_id=ctx.execution_id,
            workflow_id=ctx.workflow_id,
            phase_id=phase.phase_id,
            with_sidecar=False,  # Sidecar not needed with setup phase pattern
            inject_tokens=False,  # Handled by setup phase in container
        ) as managed_workspace:
            workspace_path = managed_workspace.path

            # Update observation context with workspace path for tracking
            obs_context = ObservationContext(
                session_id=obs_context.session_id,
                execution_id=obs_context.execution_id,
                workflow_id=obs_context.workflow_id,
                phase_id=obs_context.phase_id,
                workspace_path=str(workspace_path),
            )

            # Emit phase started
            yield PhaseStarted(
                workflow_id=ctx.workflow_id,
                execution_id=ctx.execution_id,
                phase_id=phase.phase_id,
                phase_name=phase.name,
                phase_order=phase.order,
                started_at=phase_started_at,
                workspace_path=workspace_path,
            )

            # Record phase started observation with workspace path
            await self._observability.record(
                ObservationType.EXECUTION_STARTED,
                obs_context,
                {
                    "phase_name": phase.name,
                    "phase_order": phase.order,
                    "workspace_path": str(workspace_path),
                },
            )

            # Inject context files into workspace
            for rel_path, content in phase_context_obj.to_context_files():
                file_path = workspace_path / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(content)

            # Create workspace object for agent
            workspace_config = WorkspaceConfig(
                session_id=str(uuid4()),
                base_dir=workspace_path.parent,
                workflow_id=ctx.workflow_id,
                phase_id=phase.phase_id,
            )
            workspace = Workspace(
                path=workspace_path,
                config=workspace_config,
            )

            # Create execution config
            config = AgentExecutionConfig(
                allowed_tools=phase.allowed_tools,
                max_turns=self._default_max_turns,
                max_budget_usd=self._default_max_budget_usd,
                timeout_seconds=phase.timeout_seconds,
            )

            # Execute agent with full observability
            result_text = ""
            input_tokens = 0
            output_tokens = 0
            tool_call_count = 0
            turn_number = 0

            async for event in agent.execute(task, workspace, config):
                if isinstance(event, ToolUseStarted):
                    # Record tool started via ObservabilityPort
                    operation_id = await self._observability.record_tool_started(
                        obs_context,
                        tool_name=event.tool_name,
                        tool_input=event.tool_input or {},
                    )

                    # Store operation_id for correlation (using tool_use_id as key)
                    if not hasattr(self, "_pending_tools"):
                        self._pending_tools: dict[str, tuple[str, datetime]] = {}
                    if event.tool_use_id:
                        self._pending_tools[event.tool_use_id] = (operation_id, datetime.now(UTC))

                    # Yield for SSE real-time tracking
                    yield ToolStarted(
                        workflow_id=ctx.workflow_id,
                        execution_id=ctx.execution_id,
                        phase_id=phase.phase_id,
                        tool_name=event.tool_name,
                        tool_use_id=event.tool_use_id,
                        tool_input=event.tool_input,
                        timestamp=event.timestamp,
                    )

                elif isinstance(event, ToolUseCompleted):
                    tool_call_count += 1

                    # Get operation_id from pending tools
                    operation_id = ""
                    start_time = datetime.now(UTC)
                    if hasattr(self, "_pending_tools") and event.tool_use_id:
                        pending = self._pending_tools.pop(event.tool_use_id, None)
                        if pending:
                            operation_id, start_time = pending

                    # Calculate duration
                    duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
                    if event.duration_ms:
                        duration_ms = int(event.duration_ms)

                    # Record tool completed via ObservabilityPort
                    await self._observability.record_tool_completed(
                        obs_context,
                        operation_id=operation_id,
                        tool_name=event.tool_name,
                        success=event.success,
                        duration_ms=duration_ms,
                        output_preview=event.tool_output[:500] if event.tool_output else None,
                    )

                    # Truncate long tool outputs
                    tool_output = event.tool_output
                    if tool_output and len(tool_output) > 10000:
                        tool_output = tool_output[:10000] + "... [truncated]"

                    yield ToolUsed(
                        workflow_id=ctx.workflow_id,
                        execution_id=ctx.execution_id,
                        phase_id=phase.phase_id,
                        tool_name=event.tool_name,
                        tool_use_id=event.tool_use_id,
                        success=event.success,
                        tool_output=tool_output,
                        duration_ms=event.duration_ms,
                        error=event.error,
                    )

                    # Check for control signals
                    async for ctrl_event in self._check_control_signals(ctx, phase.phase_id):
                        yield ctrl_event
                        if isinstance(ctrl_event, ExecutionCancelled):
                            return

                elif isinstance(event, ToolBlocked):
                    yield ToolBlockedExecution(
                        workflow_id=ctx.workflow_id,
                        execution_id=ctx.execution_id,
                        phase_id=phase.phase_id,
                        tool_name=event.tool_name,
                        tool_use_id=event.tool_use_id,
                        reason=event.reason,
                        validator=event.validator,
                        timestamp=event.timestamp,
                    )

                elif isinstance(event, TurnCompleted):
                    turn_number += 1

                    # Record token usage via ObservabilityPort
                    await self._observability.record_token_usage(
                        obs_context,
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                    )

                    # Emit turn update for real-time UI
                    yield TurnUpdate(
                        workflow_id=ctx.workflow_id,
                        execution_id=ctx.execution_id,
                        phase_id=phase.phase_id,
                        turn_number=turn_number,
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                        cumulative_input_tokens=event.cumulative_input_tokens,
                        cumulative_output_tokens=event.cumulative_output_tokens,
                        timestamp=event.timestamp,
                    )

                    # Check for control signals between turns
                    async for ctrl_event in self._check_control_signals(ctx, phase.phase_id):
                        yield ctrl_event
                        if isinstance(ctrl_event, ExecutionCancelled):
                            return

                elif isinstance(event, TaskCompleted):
                    result_text = event.result
                    input_tokens = event.input_tokens
                    output_tokens = event.output_tokens
                    # Capture SDK-reported cost (includes tool token costs)
                    sdk_cost = event.estimated_cost_usd

                elif isinstance(event, TaskFailed):
                    await self._observability.record(
                        ObservationType.EXECUTION_ERROR,
                        obs_context,
                        {"error": event.error, "error_type": event.error_type},
                    )
                    yield PhaseFailed(
                        workflow_id=ctx.workflow_id,
                        execution_id=ctx.execution_id,
                        phase_id=phase.phase_id,
                        failed_at=datetime.now(UTC),
                        error=event.error,
                        error_type=event.error_type,
                        partial_tokens=event.input_tokens + event.output_tokens,
                    )
                    return

            # Create artifact bundle from output
            bundle = ArtifactBundle(
                bundle_id=str(uuid4()),
                phase_id=phase.phase_id,
                workflow_id=ctx.workflow_id,
                title=f"{phase.name} Output",
            )

            # Add result as primary artifact
            from aef_adapters.artifacts import ArtifactType as AT

            bundle.add_file(
                Path(f"{phase.phase_id}_output.md"),
                result_text.encode("utf-8"),
                artifact_type=AT(phase.output_artifact_type)
                if phase.output_artifact_type in [t.value for t in AT]
                else AT.TEXT,
                is_primary=True,
            )

            # Store outputs for next phase
            ctx.phase_outputs[phase.phase_id] = result_text
            ctx.artifact_bundles.append(bundle)
            ctx.total_input_tokens += input_tokens
            ctx.total_output_tokens += output_tokens
            # Accumulate SDK cost if available
            if "sdk_cost" in dir() and sdk_cost is not None:
                ctx.total_cost_usd += Decimal(str(sdk_cost))

            # Calculate duration
            phase_completed_at = datetime.now(UTC)
            duration_ms = int((phase_completed_at - phase_started_at).total_seconds() * 1000)
            ctx.total_duration_ms += duration_ms

            # Record phase completed observation
            # Include SDK cost if available (includes tool token costs)
            sdk_cost_value = sdk_cost if "sdk_cost" in dir() and sdk_cost is not None else None
            await self._observability.record(
                ObservationType.EXECUTION_COMPLETED,
                obs_context,
                {
                    "duration_ms": duration_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "tool_call_count": tool_call_count,
                    "total_cost_usd": float(sdk_cost_value) if sdk_cost_value else None,
                },
            )

            # Emit phase completed
            completed_event = PhaseCompleted(
                workflow_id=ctx.workflow_id,
                execution_id=ctx.execution_id,
                phase_id=phase.phase_id,
                completed_at=phase_completed_at,
                artifact_bundle_id=bundle.bundle_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                duration_ms=duration_ms,
                tool_call_count=tool_call_count,
                artifact_bundle=bundle,
            )
            ctx.phase_results.append(completed_event)

            yield completed_event

    async def _check_control_signals(
        self,
        ctx: ExecutionContext,
        phase_id: str,
    ) -> AsyncIterator[ExecutionEvent]:
        """Check for control signals (pause/resume/cancel)."""
        if not self._check_signal:
            return

        from aef_adapters.control import ControlSignalType

        signal = await self._check_signal(ctx.execution_id)
        if not signal:
            return

        if signal.signal_type == ControlSignalType.PAUSE:
            yield ExecutionPaused(
                workflow_id=ctx.workflow_id,
                execution_id=ctx.execution_id,
                phase_id=phase_id,
                paused_at=datetime.now(UTC),
                reason=signal.reason,
            )
            # Wait for resume or cancel signal
            while True:
                await asyncio.sleep(CONTROL_SIGNAL_POLL_INTERVAL)
                signal = await self._check_signal(ctx.execution_id)
                if signal and signal.signal_type == ControlSignalType.RESUME:
                    yield ExecutionResumed(
                        workflow_id=ctx.workflow_id,
                        execution_id=ctx.execution_id,
                        phase_id=phase_id,
                        resumed_at=datetime.now(UTC),
                    )
                    break
                if signal and signal.signal_type == ControlSignalType.CANCEL:
                    yield ExecutionCancelled(
                        workflow_id=ctx.workflow_id,
                        execution_id=ctx.execution_id,
                        phase_id=phase_id,
                        cancelled_at=datetime.now(UTC),
                        reason=signal.reason,
                    )
                    return

        elif signal.signal_type == ControlSignalType.CANCEL:
            yield ExecutionCancelled(
                workflow_id=ctx.workflow_id,
                execution_id=ctx.execution_id,
                phase_id=phase_id,
                cancelled_at=datetime.now(UTC),
                reason=signal.reason,
            )

    def _build_task(self, phase: WorkflowPhase, ctx: ExecutionContext) -> str:
        """Build the task prompt for a phase."""
        task = phase.prompt_template

        # Substitute initial inputs
        for key, value in ctx.inputs.items():
            task = task.replace(f"{{{{{key}}}}}", str(value))

        # Substitute previous phase outputs
        for phase_id, content in ctx.phase_outputs.items():
            task = task.replace(f"{{{{{phase_id}}}}}", content)
            task = task.replace(f"{{{{{phase_id}_output}}}}", content)

        return task
