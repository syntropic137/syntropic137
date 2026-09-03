"""AgentExecutionHandler — launches container, streams output (ISS-196).

Extracted from WorkflowExecutionEngine stream processing section (lines 961-1001).
Delegates telemetry to ObservabilityCollector.

Reports AgentExecutionCompletedCommand to the aggregate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    observing_launch,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
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
from syn_shared.agents import AgentRunner

if TYPE_CHECKING:
    from syn_adapters.control import ExecutionController
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
        TodoItem,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )

logger = logging.getLogger(__name__)


def _detect_exit_code(
    stream_result: StreamResult,
    workspace: ManagedWorkspace,
    phase_id: str,
    tokens: TokenAccumulator,
) -> int:
    """Determine agent exit code from stream result and workspace state.

    Note: If interrupt_requested=True, the caller is responsible for routing
    to the cancellation path. This function returns only the actual process
    exit code.
    """
    stream_exit_code = workspace.last_stream_exit_code
    if stream_exit_code is not None and stream_exit_code != 0:
        logger.error(
            "Agent CLI exited with code %d (phase=%s, lines=%d)",
            stream_exit_code,
            phase_id,
            stream_result.line_count,
        )
        return stream_exit_code
    if tokens.input_tokens == 0 and tokens.output_tokens == 0:
        logger.warning(
            "Agent produced 0 tokens (phase=%s, lines=%d) — CLI may have failed to start",
            phase_id,
            stream_result.line_count,
        )
    return 0


def _resolve_final_totals(
    stream_result: StreamResult, tokens: TokenAccumulator
) -> tuple[int, int, int, int]:
    """Prefer authoritative result-event totals over accumulated per-turn counts."""
    return (
        stream_result.result_input_tokens or tokens.input_tokens,
        stream_result.result_output_tokens or tokens.output_tokens,
        stream_result.result_cache_creation or tokens.cache_creation_tokens,
        stream_result.result_cache_read or tokens.cache_read_tokens,
    )


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
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        runner: AgentRunner = AgentRunner.CLAUDE,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        """Run agent in workspace and stream output.

        Streams `claude_cmd` (claude -p or codex exec) through the
        workspace and parses stream-json into Lane-2 events.

        ``on_launch`` is notified once the agent process is known to exist -
        from here, not from the caller, because this is the first frame that
        can tell the difference (#1047, #1065).
        """
        assert todo.phase_id is not None

        tokens = TokenAccumulator()
        subagents = SubagentTracker()

        return await self._run_headless(
            runner=runner,
            todo=todo,
            workspace=workspace,
            agent_env=agent_env,
            claude_cmd=claude_cmd,
            session_id=session_id,
            agent_model=agent_model,
            timeout_seconds=timeout_seconds,
            collector=collector,
            tokens=tokens,
            subagents=subagents,
            on_launch=on_launch,
        )

    def _select_stream_processor(
        self,
        *,
        runner: AgentRunner,
        tokens: TokenAccumulator,
        subagents: SubagentTracker,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        session_id: str,
        agent_model: str | None,
        collector: ObservabilityCollector | None,
    ) -> EventStreamProcessor | CodexStreamProcessor:
        """Pick the codex or claude stream processor for a headless phase."""
        assert todo.phase_id is not None
        if runner == AgentRunner.CODEX:
            assert collector is not None
            return CodexStreamProcessor(
                tokens=tokens,
                collector=collector,
                controller=self._controller,
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                agent_model=agent_model,
            )
        return EventStreamProcessor(
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

    async def _run_headless(
        self,
        *,
        runner: AgentRunner,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None,
        tokens: TokenAccumulator,
        subagents: SubagentTracker,
        on_launch: AgentLaunchObserver | None,
    ) -> AgentExecutionResult:
        """Stream a headless (claude -p / codex exec) phase and build its result."""
        assert todo.phase_id is not None
        processor = self._select_stream_processor(
            runner=runner,
            tokens=tokens,
            subagents=subagents,
            todo=todo,
            workspace=workspace,
            session_id=session_id,
            agent_model=agent_model,
            collector=collector,
        )

        stream_result = await processor.process_stream(
            observing_launch(
                workspace.stream(
                    claude_cmd,
                    timeout_seconds=timeout_seconds,
                    environment=agent_env,
                ),
                on_launch,
            ),
            workspace,
        )

        exit_code = _detect_exit_code(stream_result, workspace, todo.phase_id, tokens)
        if (
            runner == AgentRunner.CODEX
            and stream_result.error_reason is not None
            and exit_code == 0
        ):
            # The codex parser reserves error_reason for a BROKEN stream
            # (malformed JSON / missing terminal turn.completed); force a
            # non-zero phase exit even when the process exit was 0.
            exit_code = 1

        # ISS-217: Emit session_summary with authoritative CLI totals (Lane 2).
        # The codex path already emits its summary inside CodexStreamProcessor
        # (single-layer), so the handler skips it for runner == "codex".
        if collector is not None and runner != AgentRunner.CODEX:
            await collector.record_session_summary(
                total_cost_usd=stream_result.total_cost_usd,
                input_tokens=stream_result.result_input_tokens,
                output_tokens=stream_result.result_output_tokens,
                cache_creation=stream_result.result_cache_creation,
                cache_read=stream_result.result_cache_read,
                num_turns=stream_result.num_turns,
                duration_ms=stream_result.duration_ms,
            )

        final_input, final_output, final_cache_creation, final_cache_read = _resolve_final_totals(
            stream_result, tokens
        )

        command = AgentExecutionCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            session_id=session_id,
            exit_code=exit_code,
            input_tokens=final_input,
            output_tokens=final_output,
            cache_creation_tokens=final_cache_creation,
            cache_read_tokens=final_cache_read,
        )

        return AgentExecutionResult(
            stream_result=stream_result,
            tokens=tokens,
            subagents=subagents,
            command=command,
        )
