"""AgentExecutionHandler — launches container, streams output (ISS-196).

Extracted from WorkflowExecutionEngine stream processing section (lines 961-1001).
Delegates telemetry to ObservabilityCollector.

Reports AgentExecutionCompletedCommand to the aggregate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    AgentExecutionCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
    AgentLaunchEvidence,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    MISSING_TERMINAL_TURN_REASON,
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


#: The only directory a phase's work survives in (ADR-036). ArtifactCollector
#: collects exactly this glob, so "did the phase produce anything" and "will
#: anything be collected" are the same question, asked of the same path.
_OUTPUT_ARTIFACT_GLOB: Final[str] = "artifacts/output/**/*"


async def _produced_deliverable(workspace: ManagedWorkspace, phase_id: str) -> bool:
    """Whether the phase left any non-empty file in artifacts/output/.

    Fails CLOSED: if the workspace cannot be read, the answer is "no", so a
    phase is never completed on the strength of a check that did not run.
    """
    try:
        collected = await workspace.collect_files(patterns=[_OUTPUT_ARTIFACT_GLOB])
    except Exception:
        logger.exception(
            "Could not read artifacts/output/ to judge a broken codex stream "
            "(phase=%s) - treating the phase as having produced nothing",
            phase_id,
        )
        return False
    return any(content for _, content in collected)


@dataclass(frozen=True)
class FinalUsage:
    """A phase's end-of-run token totals, and whether the harness itself reported them.

    Both facts are decided in one place because they must never disagree. The
    numbers say what the phase used; ``is_authoritative`` says who counted
    them, and consumers need the second to know what the first is worth:

    - **Authoritative** - the harness emitted its terminal ``result`` event and
      these are its own cumulative totals. They REPLACE anything accumulated
      mid-stream, which is the whole point of preferring them: per-turn deltas
      double-count the context re-sent on every turn, so the accumulated sum is
      normally far HIGHER than the truth.
    - **Estimated** - the process died before reporting (timeout, SIGKILL), so
      these are the deltas observed while it ran. Partial, but real: a phase
      killed after an hour of tool calls did not cost nothing (#1164).

    Collapsing the two into bare numbers is what made a killed phase read as
    $0.00 - the totals were reset to the result event's zeros, and no consumer
    could tell "spent nothing" from "never got to say".
    """

    input_tokens: int
    output_tokens: int
    cache_creation: int
    cache_read: int
    is_authoritative: bool

    @classmethod
    def resolve(cls, stream_result: StreamResult, tokens: TokenAccumulator) -> FinalUsage:
        """Take the harness's own totals when it reported them, else what was observed.

        The question is whether the harness reported, NOT how much it reported.
        Those come apart at exactly one value: a run that finished having used
        nothing reports ``0/0``, and reading that as "no report" hands its
        authoritative answer back to the accumulator, which is the opposite of
        what happened. `reported_usage` is present iff a terminal event was
        parsed, so presence is the whole test (#1164).
        """
        reported = stream_result.reported_usage
        if reported is not None:
            return cls(
                input_tokens=reported.input_tokens,
                output_tokens=reported.output_tokens,
                cache_creation=reported.cache_creation,
                cache_read=reported.cache_read,
                is_authoritative=True,
            )
        return cls(
            input_tokens=tokens.input_tokens,
            output_tokens=tokens.output_tokens,
            cache_creation=tokens.cache_creation_tokens,
            cache_read=tokens.cache_read_tokens,
            is_authoritative=False,
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

        # The launch fact is settled AFTER the stream, not while it runs: the
        # marker is announced before the exec it predicts, so only the status
        # the process finally returns says whether that exec happened (#1065).
        # `finally`, because an agent that announced itself and then blew up
        # mid-stream still existed, and the exception must not swallow that.
        #
        # The transport is told which name to announce under, rather than the
        # observer being told by the stream which name to believe. That is the
        # whole of the forgery defence: `launch.wrapper_name` exists before
        # this stream does, so no line on it can become the name that counts.
        launch = AgentLaunchEvidence(on_launch)
        try:
            stream_result = await processor.process_stream(
                launch.observing(
                    workspace.stream(
                        claude_cmd,
                        timeout_seconds=timeout_seconds,
                        environment=agent_env,
                        wrapper_name=launch.wrapper_name,
                    ),
                ),
                workspace,
            )
        finally:
            await launch.settle(workspace.last_stream_exit_code)

        exit_code = _detect_exit_code(stream_result, workspace, todo.phase_id, tokens)
        if (
            runner == AgentRunner.CODEX
            and stream_result.error_reason is not None
            and exit_code == 0
        ):
            # The codex parser reserves error_reason for a BROKEN stream
            # (malformed JSON / missing terminal turn.completed); force a
            # non-zero phase exit even when the process exit was 0.
            #
            # ONE exception (issue #1111): a stream that simply stopped before
            # `turn.completed`, having produced the phase's deliverable, is a
            # telemetry gap, not a failed phase. Failing it discards finished
            # work and skips every downstream phase - three complete codex
            # reviews were lost this way in twelve hours. An auth failure or a
            # malformed line still fails here, because it carries a DIFFERENT
            # reason and because a codex that never authenticated writes
            # nothing to artifacts/output.
            if stream_result.error_reason == MISSING_TERMINAL_TURN_REASON and (
                await _produced_deliverable(workspace, todo.phase_id)
            ):
                logger.warning(
                    "Codex stream ended without turn.completed but the phase produced "
                    "a deliverable (phase=%s) - completing with ESTIMATED usage",
                    todo.phase_id,
                )
            else:
                exit_code = 1

        # Resolved ONCE, for both lanes. The session_summary used to be written
        # straight from `stream_result.result_*` while the command below used
        # the accumulator fallback, so a killed phase reported its real tokens
        # to the aggregate and zeros to observability - and observability is
        # what the cost ledger reads (#1164).
        usage = FinalUsage.resolve(stream_result, tokens)

        # ISS-217: Emit session_summary with the phase's end-of-run totals (Lane 2).
        # The codex path already emits its summary inside CodexStreamProcessor
        # (single-layer), so the handler skips it for runner == "codex".
        #
        # `total_cost_usd` stays whatever the harness said, including None: a
        # NULL cost is priced downstream from these tokens and this model,
        # which is exactly the estimate wanted for a phase that was killed
        # before it could report one. Passing 0.0 instead would be taken as
        # authoritative and priced verbatim.
        if collector is not None and runner != AgentRunner.CODEX:
            await collector.record_session_summary(
                total_cost_usd=stream_result.total_cost_usd,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation=usage.cache_creation,
                cache_read=usage.cache_read,
                num_turns=stream_result.num_turns,
                duration_ms=stream_result.duration_ms,
                totals_are_authoritative=usage.is_authoritative,
            )

        command = AgentExecutionCompletedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            session_id=session_id,
            exit_code=exit_code,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=usage.cache_creation,
            cache_read_tokens=usage.cache_read,
        )

        return AgentExecutionResult(
            stream_result=stream_result,
            tokens=tokens,
            subagents=subagents,
            command=command,
        )
