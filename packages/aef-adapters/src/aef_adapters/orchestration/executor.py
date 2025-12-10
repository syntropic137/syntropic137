"""Agentic workflow executor using AgenticProtocol.

This executor orchestrates workflow execution using the new agentic paradigm:
- Multi-turn agent execution with tools
- Workspace isolation per execution
- Artifact bundles for phase context
- Streaming execution events

Unlike the legacy WorkflowExecutionEngine (which uses chat completion),
this executor leverages the claude-agent-sdk style execution where
agents control their own flow until task completion.

Example:
    executor = AgenticWorkflowExecutor(
        agent_factory=get_agentic_agent,
        workspace_factory=LocalWorkspace.create,
    )

    async for event in executor.execute(workflow_def, {"topic": "AI"}):
        match event:
            case WorkflowStarted():
                print(f"Started: {event.workflow_id}")
            case PhaseCompleted():
                print(f"Phase done: {event.phase_id}")
            case WorkflowCompleted():
                print(f"Done! Artifacts: {event.artifact_ids}")
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable  # noqa: TC003 - used at runtime
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

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
from aef_adapters.artifacts import ArtifactBundle, ArtifactType, PhaseContext

if TYPE_CHECKING:
    from aef_adapters.agents.agentic_protocol import AgenticProtocol
    from aef_adapters.collector import CollectorClient
    from aef_adapters.control import ControlSignal
    from aef_adapters.workspaces.protocol import WorkspaceProtocol

logger = logging.getLogger(__name__)


# ============================================================================
# Execution Events
# ============================================================================


@dataclass(frozen=True)
class WorkflowStarted:
    """Emitted when workflow execution begins."""

    workflow_id: str
    execution_id: str
    workflow_name: str
    total_phases: int
    started_at: datetime
    inputs: dict[str, Any]


@dataclass(frozen=True)
class PhaseStarted:
    """Emitted when a phase begins execution."""

    workflow_id: str
    execution_id: str
    phase_id: str
    phase_name: str
    phase_order: int
    started_at: datetime
    workspace_path: Path


@dataclass(frozen=True)
class PhaseCompleted:
    """Emitted when a phase completes successfully."""

    workflow_id: str
    execution_id: str
    phase_id: str
    completed_at: datetime
    artifact_bundle_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    duration_ms: float
    tool_call_count: int = 0
    estimated_cost_usd: Decimal | None = None
    # The full artifact bundle for persistence (optional for backwards compat)
    artifact_bundle: ArtifactBundle | None = None


@dataclass(frozen=True)
class PhaseFailed:
    """Emitted when a phase fails."""

    workflow_id: str
    execution_id: str
    phase_id: str
    failed_at: datetime
    error: str
    error_type: str | None = None
    partial_tokens: int = 0


@dataclass(frozen=True)
class WorkflowCompleted:
    """Emitted when workflow completes successfully."""

    workflow_id: str
    execution_id: str
    completed_at: datetime
    total_phases: int
    completed_phases: int
    artifact_ids: list[str]
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_duration_ms: float
    estimated_cost_usd: Decimal


@dataclass(frozen=True)
class WorkflowFailed:
    """Emitted when workflow fails."""

    workflow_id: str
    execution_id: str
    failed_at: datetime
    failed_phase_id: str | None
    error: str
    error_type: str | None
    completed_phases: int
    total_phases: int


@dataclass(frozen=True)
class ToolStarted:
    """Emitted when a tool execution begins during a phase.

    This event enables real-time tracking of tool execution in the UI
    via SSE. Pattern 2 (ADR-018) - observability events.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    tool_name: str
    tool_use_id: str | None = None
    tool_input: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ToolUsed:
    """Emitted when a tool completes execution during a phase.

    This event provides full observability of tool usage including
    outputs and duration for debugging and analytics.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    tool_name: str
    tool_use_id: str | None = None
    success: bool = True
    # Output and timing (new fields for full observability)
    tool_output: str | None = None  # Tool output (may be truncated)
    duration_ms: float | None = None  # How long the tool took
    error: str | None = None  # Error message if failed
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ToolBlockedExecution:
    """Emitted when a tool is blocked by a validator during a phase.

    This event enables real-time tracking of blocked tools in the UI
    via SSE. Pattern 2 (ADR-018) - observability events.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    tool_name: str
    tool_use_id: str | None = None
    reason: str = ""
    validator: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class TurnUpdate:
    """Emitted after each agent turn with live token metrics.

    This event enables real-time token streaming in the UI.
    Emitted after each AssistantMessage from the agent.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    turn_number: int
    # Per-turn tokens
    input_tokens: int = 0
    output_tokens: int = 0
    # Cumulative totals for this phase
    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ExecutionPaused:
    """Emitted when execution is paused via control plane."""

    workflow_id: str
    execution_id: str
    phase_id: str
    paused_at: datetime
    reason: str | None = None


@dataclass(frozen=True)
class ExecutionResumed:
    """Emitted when execution resumes after being paused."""

    workflow_id: str
    execution_id: str
    phase_id: str
    resumed_at: datetime


@dataclass(frozen=True)
class ExecutionCancelled:
    """Emitted when execution is cancelled via control plane."""

    workflow_id: str
    execution_id: str
    phase_id: str
    cancelled_at: datetime
    reason: str | None = None


# Union type for all execution events
ExecutionEvent = (
    WorkflowStarted
    | PhaseStarted
    | PhaseCompleted
    | PhaseFailed
    | WorkflowCompleted
    | WorkflowFailed
    | ToolStarted
    | ToolUsed
    | ToolBlockedExecution
    | ExecutionPaused
    | ExecutionResumed
    | ExecutionCancelled
)


# ============================================================================
# Workflow Definition Protocol
# ============================================================================


class WorkflowPhase(Protocol):
    """Protocol for workflow phase definitions."""

    @property
    def phase_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def order(self) -> int: ...

    @property
    def description(self) -> str | None: ...

    @property
    def prompt_template(self) -> str:
        """The task prompt template with {{variable}} placeholders."""
        ...

    @property
    def allowed_tools(self) -> frozenset[str]:
        """Tools this phase is allowed to use."""
        ...

    @property
    def output_artifact_type(self) -> str:
        """Type of artifact this phase produces."""
        ...

    @property
    def timeout_seconds(self) -> int: ...


class WorkflowDefinition(Protocol):
    """Protocol for workflow definitions."""

    @property
    def workflow_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def phases(self) -> list[WorkflowPhase]: ...


# ============================================================================
# Workspace Factory Protocol
# ============================================================================


class WorkspaceFactory(Protocol):
    """Protocol for creating workspaces."""

    async def __call__(
        self,
        base_path: Path,
        *,
        execution_id: str,
        phase_id: str,
    ) -> WorkspaceProtocol:
        """Create a workspace for phase execution."""
        ...


# ============================================================================
# Execution Context
# ============================================================================


@dataclass
class ExecutionContext:
    """Mutable context for tracking execution state."""

    workflow_id: str
    execution_id: str
    workflow_name: str
    started_at: datetime
    inputs: dict[str, Any]

    # Phase tracking
    phase_results: list[PhaseCompleted | PhaseFailed] = field(default_factory=list)
    artifact_bundles: list[ArtifactBundle] = field(default_factory=list)
    phase_outputs: dict[str, str] = field(default_factory=dict)

    # Metrics
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_duration_ms: float = 0.0


# ============================================================================
# Agentic Workflow Executor
# ============================================================================


class AgenticWorkflowExecutor:
    """Executes workflows using the AgenticProtocol.

    This executor orchestrates multi-phase workflows where each phase
    is executed by an agentic agent that can use tools, make multiple
    turns, and produce artifacts.

    Key differences from legacy WorkflowExecutionEngine:
    - Uses AgenticProtocol instead of chat completion
    - Streams execution events
    - Manages workspaces per execution
    - Handles artifact bundles for context flow
    - Sends tool events to Collector for observability (when configured)

    Example:
        executor = AgenticWorkflowExecutor(
            agent_factory=get_agentic_agent,
            workspace_factory=LocalWorkspace.create,
            base_workspace_path=Path("/tmp/aef-workspaces"),
            collector_url="http://localhost:8080",  # Optional
        )

        async for event in executor.execute(workflow, {"topic": "AI agents"}):
            print(event)
    """

    def __init__(
        self,
        agent_factory: Callable[[str], AgenticProtocol],
        workspace_factory: Callable[..., WorkspaceProtocol],
        *,
        base_workspace_path: Path | None = None,
        default_provider: str = "claude",
        default_max_turns: int = 50,
        default_max_budget_usd: float | None = None,
        collector_url: str | None = None,
        control_signal_checker: Callable[[str], Awaitable[ControlSignal | None]] | None = None,
    ) -> None:
        """Initialize the executor.

        Args:
            agent_factory: Factory for creating agentic agents.
            workspace_factory: Factory for creating workspaces.
            base_workspace_path: Base path for workspace directories.
            default_provider: Default agent provider.
            default_max_turns: Default max turns per phase.
            default_max_budget_usd: Default max budget per phase.
            collector_url: Optional URL for Collector service (observability).
                          When set, tool events are sent to the Collector.
            control_signal_checker: Optional callback to check for control signals
                          (pause/resume/cancel). Called after each tool event.
        """
        self._agent_factory = agent_factory
        self._workspace_factory = workspace_factory
        self._base_path = base_workspace_path or Path.cwd() / ".aef-workspaces"
        self._default_provider = default_provider
        self._default_max_turns = default_max_turns
        self._default_max_budget_usd = default_max_budget_usd
        self._collector_url = collector_url
        self._collector: CollectorClient | None = None
        self._check_signal = control_signal_checker

    async def execute(
        self,
        workflow: WorkflowDefinition,
        inputs: dict[str, Any],
        *,
        execution_id: str | None = None,
        provider: str | None = None,
    ) -> AsyncIterator[ExecutionEvent]:
        """Execute a workflow, yielding events as execution progresses.

        Args:
            workflow: The workflow definition to execute.
            inputs: Initial input variables.
            execution_id: Optional custom execution ID.
            provider: Optional agent provider override.

        Yields:
            ExecutionEvent instances as execution progresses.
        """
        # Initialize collector client if URL is configured
        if self._collector_url and self._collector is None:
            from aef_adapters.collector import CollectorClient

            self._collector = CollectorClient(
                collector_url=self._collector_url,
                agent_id=f"executor-{workflow.workflow_id[:8]}",
            )
            await self._collector.start()
            logger.info(
                "Collector client started for observability",
                extra={"collector_url": self._collector_url},
            )

        try:
            async for event in self._execute_workflow(workflow, inputs, execution_id, provider):
                yield event
        finally:
            # Flush and close collector on completion
            if self._collector:
                try:
                    await self._collector.close()
                    logger.debug("Collector client closed")
                except Exception as e:
                    logger.warning("Failed to close collector client: %s", e)
                self._collector = None

    async def _execute_workflow(
        self,
        workflow: WorkflowDefinition,
        inputs: dict[str, Any],
        execution_id: str | None,
        provider: str | None,
    ) -> AsyncIterator[ExecutionEvent]:
        """Internal workflow execution logic."""
        # Initialize context
        ctx = ExecutionContext(
            workflow_id=workflow.workflow_id,
            execution_id=execution_id or str(uuid4()),
            workflow_name=workflow.name,
            started_at=datetime.now(UTC),
            inputs=inputs,
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
            try:
                async for event in self._execute_phase(agent, phase, ctx):
                    yield event

                    # Check for phase failure
                    if isinstance(event, PhaseFailed):
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
            estimated_cost_usd=Decimal("0"),  # TODO: Calculate from model config
        )

    async def _execute_phase(
        self,
        agent: AgenticProtocol,
        phase: WorkflowPhase,
        ctx: ExecutionContext,
    ) -> AsyncIterator[ExecutionEvent]:
        """Execute a single phase.

        Yields:
            PhaseStarted, then either PhaseCompleted or PhaseFailed.
        """
        phase_started_at = datetime.now(UTC)

        # Create workspace for this phase
        workspace_path = self._base_path / ctx.execution_id / phase.phase_id
        workspace_path.mkdir(parents=True, exist_ok=True)

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

        # Build task prompt
        task = self._build_task(phase, ctx)

        # Create phase context with previous artifacts
        phase_context = PhaseContext(
            task=task,
            phase_id=phase.phase_id,
            workflow_id=ctx.workflow_id,
            artifacts=ctx.artifact_bundles,
        )

        # Inject context files into workspace
        for rel_path, content in phase_context.to_context_files():
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

        # Execute agent
        # Use execution_id as session_id for collector correlation
        session_id = ctx.execution_id
        result_text = ""
        input_tokens = 0
        output_tokens = 0
        tool_call_count = 0

        async for event in agent.execute(task, workspace, config):
            if isinstance(event, ToolUseStarted):
                # Send tool_execution_started to Collector for observability
                if self._collector:
                    try:
                        await self._collector.send_tool_started(
                            session_id=session_id,
                            tool_name=event.tool_name,
                            tool_use_id=event.tool_use_id or "",
                            tool_input=event.tool_input,
                            timestamp=event.timestamp,
                        )
                    except Exception as e:
                        logger.warning("Failed to send tool_started to collector: %s", e)

                # Yield for SSE real-time tracking (Pattern 2)
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
                # Emit tool used event for real-time tracking with full observability
                tool_call_count += 1

                # Send tool_execution_completed to Collector
                if self._collector:
                    try:
                        await self._collector.send_tool_completed(
                            session_id=session_id,
                            tool_name=event.tool_name,
                            tool_use_id=event.tool_use_id or "",
                            duration_ms=int(event.duration_ms),
                            success=event.success,
                            error_message=event.error,
                            timestamp=event.timestamp,
                        )
                    except Exception as e:
                        logger.warning("Failed to send tool_completed to collector: %s", e)

                # Truncate long tool outputs (keep under 10KB for storage)
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

                # Check for control signals after each tool event
                if self._check_signal:
                    from aef_adapters.control import ControlSignalType

                    signal = await self._check_signal(ctx.execution_id)
                    if signal:
                        if signal.signal_type == ControlSignalType.PAUSE:
                            yield ExecutionPaused(
                                workflow_id=ctx.workflow_id,
                                execution_id=ctx.execution_id,
                                phase_id=phase.phase_id,
                                paused_at=datetime.now(UTC),
                                reason=signal.reason,
                            )
                            # Wait for resume or cancel signal
                            while True:
                                await asyncio.sleep(1)
                                signal = await self._check_signal(ctx.execution_id)
                                if signal and signal.signal_type == ControlSignalType.RESUME:
                                    yield ExecutionResumed(
                                        workflow_id=ctx.workflow_id,
                                        execution_id=ctx.execution_id,
                                        phase_id=phase.phase_id,
                                        resumed_at=datetime.now(UTC),
                                    )
                                    break
                                if signal and signal.signal_type == ControlSignalType.CANCEL:
                                    yield ExecutionCancelled(
                                        workflow_id=ctx.workflow_id,
                                        execution_id=ctx.execution_id,
                                        phase_id=phase.phase_id,
                                        cancelled_at=datetime.now(UTC),
                                        reason=signal.reason,
                                    )
                                    return  # Exit phase execution
                        elif signal.signal_type == ControlSignalType.CANCEL:
                            yield ExecutionCancelled(
                                workflow_id=ctx.workflow_id,
                                execution_id=ctx.execution_id,
                                phase_id=phase.phase_id,
                                cancelled_at=datetime.now(UTC),
                                reason=signal.reason,
                            )
                            return  # Exit phase execution

            elif isinstance(event, ToolBlocked):
                # Send tool_blocked to Collector
                if self._collector:
                    try:
                        await self._collector.send_tool_blocked(
                            session_id=session_id,
                            tool_name=event.tool_name,
                            tool_use_id=event.tool_use_id or "",
                            reason=event.reason,
                            validator_name=event.validator,
                            timestamp=event.timestamp,
                        )
                    except Exception as e:
                        logger.warning("Failed to send tool_blocked to collector: %s", e)

                # Yield for SSE real-time tracking (Pattern 2)
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
                # Emit live token update for real-time UI streaming
                yield TurnUpdate(
                    workflow_id=ctx.workflow_id,
                    execution_id=ctx.execution_id,
                    phase_id=phase.phase_id,
                    turn_number=event.turn_number,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                    cumulative_input_tokens=event.cumulative_input_tokens,
                    cumulative_output_tokens=event.cumulative_output_tokens,
                    timestamp=event.timestamp,
                )

                # TODO: Check for control signals here (pause/cancel)
                # This is where we can make execution interruptible between turns
                # if self._signal_port:
                #     signal = await self._signal_port.get_signal(ctx.execution_id)
                #     if signal and signal.action == "cancel":
                #         yield ExecutionCancelled(...)
                #         return

            elif isinstance(event, TaskCompleted):
                result_text = event.result
                input_tokens = event.input_tokens
                output_tokens = event.output_tokens

            elif isinstance(event, TaskFailed):
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
        bundle.add_file(
            Path(f"{phase.phase_id}_output.md"),
            result_text.encode("utf-8"),
            artifact_type=ArtifactType(phase.output_artifact_type)
            if phase.output_artifact_type in [t.value for t in ArtifactType]
            else ArtifactType.TEXT,
            is_primary=True,
        )

        # Store outputs for next phase
        ctx.phase_outputs[phase.phase_id] = result_text
        ctx.artifact_bundles.append(bundle)
        ctx.total_input_tokens += input_tokens
        ctx.total_output_tokens += output_tokens

        # Calculate duration
        phase_completed_at = datetime.now(UTC)
        duration_ms = (phase_completed_at - phase_started_at).total_seconds() * 1000
        ctx.total_duration_ms += duration_ms

        # Emit phase completed with full bundle for persistence
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
            artifact_bundle=bundle,  # Include full bundle for downstream persistence
        )
        ctx.phase_results.append(completed_event)

        yield completed_event

    def _build_task(self, phase: WorkflowPhase, ctx: ExecutionContext) -> str:
        """Build the task prompt for a phase.

        Substitutes template variables with:
        - Initial workflow inputs
        - Previous phase outputs
        """
        task = phase.prompt_template

        # Substitute initial inputs
        for key, value in ctx.inputs.items():
            task = task.replace(f"{{{{{key}}}}}", str(value))

        # Substitute previous phase outputs
        for phase_id, content in ctx.phase_outputs.items():
            task = task.replace(f"{{{{{phase_id}}}}}", content)
            task = task.replace(f"{{{{{phase_id}_output}}}}", content)

        return task
