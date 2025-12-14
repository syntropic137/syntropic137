"""AgentExecutor - abstraction for running agents in isolated workspaces.

Per ADR-023, agents MUST run inside isolated workspaces. This module provides
the abstraction for agent execution within workspace boundaries.

The AgentExecutor protocol defines how agents are launched and monitored
inside isolated environments (Docker, gVisor, Firecracker, etc.).

See ADR-023: Workspace-First Execution Model
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal  # noqa: TC003 - used in dataclass field type
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_adapters.agents.agentic_types import AgentExecutionConfig
    from aef_adapters.workspaces.types import IsolatedWorkspace

logger = logging.getLogger(__name__)


# =============================================================================
# EXECUTION RESULT
# =============================================================================


@dataclass
class AgentExecutionMetrics:
    """Metrics from agent execution."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    turns_used: int = 0
    duration_seconds: float = 0.0
    estimated_cost_usd: Decimal | None = None
    tools_used: list[str] = field(default_factory=list)


@dataclass
class WorkspaceExecutionResult:
    """Result of agent execution inside a workspace.

    This is the unified result type for all agent executors,
    regardless of underlying implementation.
    """

    # Core result
    success: bool
    output: str
    error_message: str | None = None

    # Execution context
    workspace_id: str | None = None
    execution_id: str | None = None
    session_id: str | None = None

    # Metrics
    metrics: AgentExecutionMetrics = field(default_factory=AgentExecutionMetrics)

    # Artifacts produced
    artifact_paths: list[str] = field(default_factory=list)

    # Timing
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


# =============================================================================
# EXECUTION EVENTS (for streaming)
# =============================================================================


@dataclass
class ExecutionEvent:
    """Base class for execution events."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ExecutionStarted(ExecutionEvent):
    """Agent execution has started."""

    workspace_id: str | None = None
    task: str = ""


@dataclass
class ExecutionProgress(ExecutionEvent):
    """Progress update during execution."""

    message: str = ""
    turn_number: int = 0
    tokens_used: int = 0


@dataclass
class ExecutionOutput(ExecutionEvent):
    """Output from agent during execution."""

    content: str = ""
    is_partial: bool = True


@dataclass
class ExecutionToolUse(ExecutionEvent):
    """Agent used a tool."""

    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    success: bool = True


@dataclass
class ExecutionCompleted(ExecutionEvent):
    """Agent execution completed."""

    result: WorkspaceExecutionResult = field(
        default_factory=lambda: WorkspaceExecutionResult(success=False, output="")
    )


# =============================================================================
# EXECUTOR PROTOCOL
# =============================================================================


@runtime_checkable
class AgentExecutor(Protocol):
    """Protocol for executing agents inside isolated workspaces.

    Implementations:
    - ClaudeAgentExecutor: Uses claude-agent-sdk subprocess in workspace
    - MockAgentExecutor: For testing without real agent

    See ADR-023: Workspace-First Execution Model
    """

    @abstractmethod
    async def execute(
        self,
        task: str,
        workspace: IsolatedWorkspace,
        config: AgentExecutionConfig,
        *,
        execution_id: str | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[ExecutionEvent]:
        """Execute an agent task inside an isolated workspace.

        The agent runs INSIDE the workspace's isolation boundary,
        with access to the workspace filesystem and network policy.

        Args:
            task: Natural language task description
            workspace: Isolated workspace (Docker, gVisor, etc.)
            config: Execution configuration (model, limits, tools)
            execution_id: Optional execution ID for correlation
            session_id: Optional session ID for tracking

        Yields:
            ExecutionEvent stream (progress, output, tool use, completion)

        Raises:
            AgentExecutionError: If execution fails
            RuntimeError: If workspace is not properly isolated
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the agent provider name (e.g., 'claude', 'openai')."""
        ...


# =============================================================================
# EXCEPTIONS
# =============================================================================


class AgentExecutionError(Exception):
    """Error during agent execution in workspace."""

    def __init__(
        self,
        message: str,
        *,
        workspace_id: str | None = None,
        execution_id: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.workspace_id = workspace_id
        self.execution_id = execution_id
        self.__cause__ = cause


class AgentNotAvailableError(AgentExecutionError):
    """Agent provider not available or not configured."""

    pass


class AgentBudgetExceededError(AgentExecutionError):
    """Agent exceeded budget limit."""

    def __init__(
        self,
        message: str,
        *,
        budget_usd: Decimal,
        spent_usd: Decimal,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.budget_usd = budget_usd
        self.spent_usd = spent_usd
