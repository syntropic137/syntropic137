"""AgentExecutionHandler — launches container, streams output (ISS-196).

Extracted from WorkflowExecutionEngine stream processing section (lines 961-1001).
Delegates telemetry to ObservabilityCollector.

Reports AgentExecutionCompletedCommand to the aggregate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

if TYPE_CHECKING:
    from syn_adapters.control import ExecutionController
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
        TodoItem,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )

logger = logging.getLogger(__name__)


class AgentExecutionResult:
    """Result of agent execution."""

    __slots__ = ("command", "stream_result", "subagents", "tokens")

    def __init__(
        self,
        stream_result: StreamResult,
        tokens: TokenAccumulator,
        subagents: SubagentTracker,
        command: AgentExecutionCompletedCommand,
    ) -> None:
        self.stream_result = stream_result
        self.tokens = tokens
        self.subagents = subagents
        self.command = command


class AgentExecutionHandler:
    """Launches agent in container, streams output via EventStreamProcessor.

    Reports AgentExecutionCompletedCommand.
    """

    def __init__(
        self,
        controller: ExecutionController | None,
    ) -> None:
        self._controller = controller

    async def handle(
        self,
        todo: TodoItem,
        workspace: Any,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
    ) -> AgentExecutionResult:
        """Run agent in workspace and stream output.

        Args:
            todo: The to-do item being processed
            workspace: Active workspace with stream() method
            agent_env: Environment variables for the agent
            claude_cmd: Claude CLI command to execute
            session_id: Session ID for observability
            agent_model: Agent model name
            timeout_seconds: Phase timeout
            collector: Observability collector for Lane 2 telemetry

        Returns:
            AgentExecutionResult with stream result, tokens, and aggregate command
        """
        assert todo.phase_id is not None

        tokens = TokenAccumulator()
        subagents = SubagentTracker()

        processor = EventStreamProcessor(
            tokens=tokens,
            subagents=subagents,
            observability=None,  # Not used when collector is provided
            controller=self._controller,
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            session_id=session_id,
            workspace_id=getattr(workspace, "id", None),
            agent_model=agent_model,
            collector=collector,
        )

        stream_result = await processor.process_stream(
            workspace.stream(
                claude_cmd,
                timeout_seconds=timeout_seconds,
                environment=agent_env,
            ),
            workspace,
        )

        # Detect agent failure: CLI exited with non-zero, or produced no output
        stream_exit_code = workspace.last_stream_exit_code
        if stream_result.interrupt_requested:
            exit_code = 1
        elif stream_exit_code is not None and stream_exit_code != 0:
            logger.error(
                "Agent CLI exited with code %d (phase=%s, lines=%d)",
                stream_exit_code,
                todo.phase_id,
                stream_result.line_count,
            )
            exit_code = stream_exit_code
        else:
            exit_code = 0
            if tokens.input_tokens == 0 and tokens.output_tokens == 0:
                logger.warning(
                    "Agent produced 0 tokens (phase=%s, lines=%d) — CLI may have failed to start",
                    todo.phase_id,
                    stream_result.line_count,
                )

        command = AgentExecutionCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            session_id=session_id,
            exit_code=exit_code,
            input_tokens=tokens.input_tokens,
            output_tokens=tokens.output_tokens,
        )

        return AgentExecutionResult(
            stream_result=stream_result,
            tokens=tokens,
            subagents=subagents,
            command=command,
        )
