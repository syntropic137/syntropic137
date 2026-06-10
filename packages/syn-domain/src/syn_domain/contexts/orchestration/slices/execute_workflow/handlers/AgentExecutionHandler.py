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
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration._shared.TodoValueObjects import (
        TodoItem,
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
        agent_model: str,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        interactive_prompt: str | None = None,
    ) -> AgentExecutionResult:
        """Run agent in workspace and stream output.

        Dispatch:
          * `interactive_prompt is None` (default) → claude -p path:
            stream `claude_cmd` through the workspace, parse stream-json
            into Lane-2 events.
          * `interactive_prompt is not None` → interactive-tmux path:
            drive the workspace's interactive-tmux driver via
            send_message / await_completion / capture_response and
            synthesize a single Lane-2 capture event. Token/cost
            accounting is not available on this path in v1
            (see docs/plans/interactive-tmux-integration.md §7).
        """
        assert todo.phase_id is not None

        tokens = TokenAccumulator()
        subagents = SubagentTracker()

        if interactive_prompt is not None:
            return await self._handle_interactive(
                todo=todo,
                workspace=workspace,
                tokens=tokens,
                subagents=subagents,
                prompt=interactive_prompt,
                session_id=session_id,
                timeout_seconds=timeout_seconds,
                collector=collector,
            )

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

        exit_code = _detect_exit_code(stream_result, workspace, todo.phase_id, tokens)

        # ISS-217: Emit session_summary with authoritative CLI totals (Lane 2)
        if collector is not None:
            await collector.record_session_summary(
                total_cost_usd=stream_result.total_cost_usd,
                input_tokens=stream_result.result_input_tokens,
                output_tokens=stream_result.result_output_tokens,
                cache_creation=stream_result.result_cache_creation,
                cache_read=stream_result.result_cache_read,
                num_turns=stream_result.num_turns,
                duration_ms=stream_result.duration_ms,
            )

        # Prefer result event totals (authoritative) over accumulated per-turn counts
        final_input = stream_result.result_input_tokens or tokens.input_tokens
        final_output = stream_result.result_output_tokens or tokens.output_tokens
        final_cache_creation = stream_result.result_cache_creation or tokens.cache_creation_tokens
        final_cache_read = stream_result.result_cache_read or tokens.cache_read_tokens

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

    async def _handle_interactive(
        self,
        *,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        tokens: TokenAccumulator,
        subagents: SubagentTracker,
        prompt: str,
        session_id: str,
        timeout_seconds: int,
        collector: ObservabilityCollector | None,
    ) -> AgentExecutionResult:
        """Drive a claude-interactive phase through send_message/await_completion.

        Routes through `InteractiveTmuxIsolationAdapter.provider_handle(...)`
        — public accessor, no `_handle` reach-ins. Falls back to the
        standard agent path with a recorded error if the workspace is
        not actually backed by the interactive provider.
        """
        assert todo.phase_id is not None

        from typing import Any, cast

        adapter = getattr(workspace, "_service", None)
        adapter = getattr(adapter, "_isolation", None)
        get_handle = getattr(adapter, "provider_handle", None)
        driver: Any = None
        if callable(get_handle):
            driver = cast("Any", get_handle(workspace.isolation_handle))

        if driver is None:
            error_msg = (
                "interactive-tmux dispatch invoked but the workspace's "
                "isolation backend does not expose provider_handle "
                "(expected InteractiveTmuxIsolationAdapter). "
                "Check SYN_WORKSPACE_INTERACTIVE_TMUX_ENABLED and "
                "WorkspaceServiceConfig.provider_kind."
            )
            logger.error(error_msg)
            stream_result = StreamResult(
                line_count=0,
                interrupt_requested=False,
                interrupt_reason=None,
                agent_task_result=None,
                error_reason=error_msg,
            )
            command = AgentExecutionCompletedCommand(
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                exit_code=1,
                input_tokens=0,
                output_tokens=0,
                cache_creation_tokens=0,
                cache_read_tokens=0,
            )
            return AgentExecutionResult(
                stream_result=stream_result,
                tokens=tokens,
                subagents=subagents,
                command=command,
            )

        import asyncio

        loop = asyncio.get_running_loop()

        def _drive() -> tuple[int, str, str]:
            driver.send_message("claude", prompt)
            result = driver.await_completion("claude", timeout=float(timeout_seconds))
            pane = driver.capture_response("claude")
            exit_code = 0 if result.ready else 124  # 124 = standard timeout exit code
            reason = getattr(result, "reason", "ready" if result.ready else "timeout")
            return exit_code, pane, reason

        exit_code, pane, reason = await loop.run_in_executor(None, _drive)

        if collector is not None:
            await collector.record_session_summary(
                total_cost_usd=0.0,
                input_tokens=0,
                output_tokens=0,
                cache_creation=0,
                cache_read=0,
                num_turns=1,
                duration_ms=0,
            )

        logger.info(
            "interactive-tmux phase finished (phase=%s, exit=%d, reason=%s, pane_chars=%d)",
            todo.phase_id,
            exit_code,
            reason,
            len(pane),
        )

        # Persist the pane capture as conversation content so the phase's
        # actual response survives into conversation storage. Wrapped as a
        # single synthetic JSONL line because ConversationRecorder stores
        # JSONL (the claude -p path stores raw stream-json lines).
        import json

        conversation_lines: list[str] = []
        if pane:
            conversation_lines.append(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": pane}],
                        },
                        "source": "interactive-tmux-capture",
                    }
                )
            )

        error_reason = (
            None
            if exit_code == 0
            else (
                f"interactive-tmux await_completion did not become ready "
                f"within {timeout_seconds}s (reason={reason})"
            )
        )

        stream_result = StreamResult(
            line_count=len(conversation_lines),
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
            conversation_lines=conversation_lines,
            num_turns=1,
            error_reason=error_reason,
        )
        command = AgentExecutionCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            session_id=session_id,
            exit_code=exit_code,
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
        )
        return AgentExecutionResult(
            stream_result=stream_result,
            tokens=tokens,
            subagents=subagents,
            command=command,
        )
