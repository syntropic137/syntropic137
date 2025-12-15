"""ClaudeAgentExecutor - executes Claude agents inside isolated workspaces.

Per ADR-023, this executor runs the Claude agent inside the workspace's
isolation boundary, not in the host process.

For now, this uses the claude-agent-sdk with cwd set to the workspace path.
Future versions may use subprocess execution inside the container.

See ADR-023: Workspace-First Execution Model
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from aef_adapters.agents.executor import (
    AgentExecutionError,
    AgentExecutionMetrics,
    AgentNotAvailableError,
    ExecutionCompleted,
    ExecutionOutput,
    ExecutionProgress,
    ExecutionStarted,
    ExecutionToolUse,
    WorkspaceExecutionResult,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_adapters.agents.agentic_types import AgentExecutionConfig
    from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent
    from aef_adapters.agents.executor import ExecutionEvent
    from aef_adapters.workspace_backends.service import ManagedWorkspace

logger = logging.getLogger(__name__)


class ClaudeAgentExecutor:
    """Executes Claude agents inside isolated workspaces.

    This executor wraps ClaudeAgenticAgent and ensures execution
    happens within the workspace isolation boundary.

    Example:
        executor = ClaudeAgentExecutor()

        async with router.create(config) as workspace:
            async for event in executor.execute(
                task="Create hello.py",
                workspace=workspace,
                config=execution_config,
            ):
                if isinstance(event, ExecutionCompleted):
                    print(f"Result: {event.result.output}")
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize Claude agent executor.

        Args:
            model: Model name or alias (default: claude-haiku)
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        self._model = model
        self._api_key = api_key
        self._agent: ClaudeAgenticAgent | None = None  # Lazy init

    @property
    def provider_name(self) -> str:
        """Get the agent provider name."""
        return "claude"

    def _get_agent(self) -> ClaudeAgenticAgent:
        """Get or create the underlying Claude agent."""
        if self._agent is None:
            from aef_adapters.agents.claude_agentic import ClaudeAgenticAgent

            self._agent = ClaudeAgenticAgent(
                model=self._model,
                api_key=self._api_key,
            )
        return self._agent

    async def execute(
        self,
        task: str,
        workspace: ManagedWorkspace,
        config: AgentExecutionConfig,
        *,
        execution_id: str | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[ExecutionEvent]:
        """Execute a task inside the isolated workspace.

        Args:
            task: Natural language task description
            workspace: Isolated workspace (Docker, gVisor, etc.)
            config: Execution configuration
            execution_id: Optional execution ID for correlation
            session_id: Optional session ID for tracking

        Yields:
            ExecutionEvent stream
        """
        from aef_adapters.agents.agentic_types import (
            TaskCompleted,
            TaskFailed,
            TextOutput,
            ToolUseCompleted,
            ToolUseStarted,
            TurnCompleted,
            Workspace,
        )

        agent = self._get_agent()

        if not agent.is_available:
            raise AgentNotAvailableError(
                "Claude agent not available. Check ANTHROPIC_API_KEY.",
                workspace_id=workspace.workspace_id,
                execution_id=execution_id,
            )

        # Emit started event
        yield ExecutionStarted(
            workspace_id=workspace.workspace_id,
            task=task,
        )

        start_time = time.time()
        workspace_id = workspace.workspace_id

        # Adapt ManagedWorkspace to Workspace for the underlying agent
        # Note: ManagedWorkspace handles execution internally - this adapter
        # bridges to the legacy Workspace interface for backward compatibility
        workspace_path_str = (
            workspace.isolation_handle.workspace_path
            if workspace.isolation_handle and workspace.isolation_handle.workspace_path
            else "/workspace"
        )
        adapted_workspace = Workspace(
            path=Path(workspace_path_str),
            config=None,  # type: ignore[arg-type]
        )

        result_output = ""
        error_message: str | None = None
        success = False
        metrics = AgentExecutionMetrics()
        artifact_paths: list[str] = []

        try:
            async for event in agent.execute(
                task=task,
                workspace=adapted_workspace,
                config=config,
            ):
                if isinstance(event, TextOutput):
                    yield ExecutionOutput(
                        content=event.content,
                        is_partial=event.is_partial,
                    )

                elif isinstance(event, ToolUseStarted):
                    yield ExecutionToolUse(
                        tool_name=event.tool_name,
                        tool_input=event.tool_input,
                        success=True,  # Updated on completion
                    )

                elif isinstance(event, ToolUseCompleted):
                    # Track tools used
                    metrics.tools_used.append(event.tool_name)

                elif isinstance(event, TurnCompleted):
                    yield ExecutionProgress(
                        message=f"Turn {event.turn_number} completed",
                        turn_number=event.turn_number,
                        tokens_used=event.cumulative_input_tokens + event.cumulative_output_tokens,
                    )
                    metrics.turns_used = event.turn_number

                elif isinstance(event, TaskCompleted):
                    success = True
                    result_output = event.result
                    metrics.input_tokens = event.input_tokens
                    metrics.output_tokens = event.output_tokens
                    metrics.total_tokens = event.total_tokens
                    metrics.turns_used = event.turns_used
                    metrics.duration_seconds = event.duration_ms / 1000.0
                    if event.estimated_cost_usd is not None:
                        metrics.estimated_cost_usd = Decimal(str(event.estimated_cost_usd))

                elif isinstance(event, TaskFailed):
                    success = False
                    error_message = event.error
                    result_output = event.partial_result or ""
                    metrics.input_tokens = event.input_tokens
                    metrics.output_tokens = event.output_tokens
                    metrics.turns_used = event.turns_used
                    metrics.duration_seconds = event.duration_ms / 1000.0

        except Exception as e:
            success = False
            error_message = str(e)
            metrics.duration_seconds = time.time() - start_time
            logger.exception("Agent execution failed", extra={"workspace_id": workspace_id})

        # Calculate final duration if not set
        if metrics.duration_seconds == 0.0:
            metrics.duration_seconds = time.time() - start_time

        # Build final result
        result = WorkspaceExecutionResult(
            success=success,
            output=result_output,
            error_message=error_message,
            workspace_id=workspace_id,
            execution_id=execution_id,
            session_id=session_id,
            metrics=metrics,
            artifact_paths=artifact_paths,
            started_at=datetime.fromtimestamp(start_time, tz=UTC),
            completed_at=datetime.now(UTC),
        )

        # Emit completed event
        yield ExecutionCompleted(result=result)

        if not success and error_message:
            raise AgentExecutionError(
                error_message,
                workspace_id=workspace_id,
                execution_id=execution_id,
            )


# Factory function
_default_executor: ClaudeAgentExecutor | None = None


def get_claude_executor(
    model: str | None = None,
    api_key: str | None = None,
) -> ClaudeAgentExecutor:
    """Get a Claude agent executor.

    Args:
        model: Optional model override
        api_key: Optional API key override

    Returns:
        ClaudeAgentExecutor instance
    """
    global _default_executor

    # If custom args, create new instance
    if model is not None or api_key is not None:
        return ClaudeAgentExecutor(model=model, api_key=api_key)

    # Otherwise use singleton
    if _default_executor is None:
        _default_executor = ClaudeAgentExecutor()

    return _default_executor


def reset_claude_executor() -> None:
    """Reset the default executor (for testing)."""
    global _default_executor
    _default_executor = None
