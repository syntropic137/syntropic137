"""What a RAW harness stream has to contain before its phase may be re-run (#1303, #1344).

`test_agent_attempts.py` pins the retry rule against a scripted double, which
announces work by calling the collector directly. That is the right level for
"which result does the caller get", and the wrong level for this question: the
double announces only the activity a test remembered to give it, so it can
prove the rule is applied and can never prove the rule is asked about the right
thing.

The defect it therefore could not catch, found by the second cross-model review
of #1344: the "did this attempt do anything" witness recognised only tool calls
it had a branch for and assistant text it had parsed, and read the absence of
those particular shapes as silence. Real streams carry others. A claude tool
call delivered over the HOOK channel, a turn whose content is only `thinking`,
a content block type shipped after the parser was written, a codex item that
starts and never completes, a codex item type nobody has taught it - every one
of them was an agent that had got somewhere, reported as an agent that had
never started, and re-run from the top over the workspace it had already
changed.

So each case here is RAW JSONL, fed through the real stream processor into the
real collector that `run_phase_agent` built, and each asserts the same thing:
the busy upstream did NOT buy a second attempt. The control at the bottom is
what stops all of that passing on a change that simply retries nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.orchestration import (
    AgentExecutionCompletedCommand,
    AgentExecutionResult,
    SubagentTracker,
    TokenAccumulator,
)
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_attempts import (
    run_phase_agent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.busy_upstream import (
    UpstreamRetryPolicy,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    CodexStreamProcessor,
    codex_fault_reason,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseLaunch
from syn_domain.contexts.orchestration.slices.execute_workflow.test_agent_attempts import (
    started_session_manager,
)
from syn_shared.agents import AgentProvider, AgentRunner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
        AgentHandlerProtocol,
        Runner,
    )

# CI selects with `pytest -m unit`; without this the whole module is collected
# by no job and can fail on main behind a green check (#825).
pytestmark = pytest.mark.unit

#: Zero backoff. What the schedule is costs 15 seconds a test and is pinned in
#: `test_busy_upstream.py`; what is under test here is the count of attempts.
NO_WAITING = UpstreamRetryPolicy(base_delay_seconds=0.0)

#: The busy fault, as a RAW claude terminal line rather than as the string the
#: parser makes of it. Driving the parser is the point: a fixture that supplied
#: "API overloaded (HTTP 529)" directly would pass whatever the parser did.
CLAUDE_OVERLOADED_LINE = json.dumps(
    {
        "type": "result",
        "is_error": True,
        "result": (
            'API Error: 529 {"type":"error","error":'
            '{"type":"overloaded_error","message":"Overloaded"}}'
        ),
    }
)

#: The same, for codex: the sentence observed in #1303, on the event codex
#: really puts it on.
CODEX_AT_CAPACITY_LINE = json.dumps(
    {
        "type": "turn.failed",
        "error": {"message": "Selected model is at capacity. Please try a different model."},
    }
)

#: What the codex parser makes of the line above.
CODEX_AT_CAPACITY = codex_fault_reason(
    "Selected model is at capacity. Please try a different model."
)


def _claude_assistant(*content: dict[str, object], message_id: str = "msg-1") -> str:
    """One raw claude assistant line carrying ``content`` verbatim."""
    return json.dumps(
        {"type": "assistant", "message": {"id": message_id, "content": list(content)}}
    )


def _claude_hook(event_type: str, **context: object) -> str:
    """One raw standalone hook JSONL line, as the in-container hooks emit it."""
    return json.dumps(
        {
            "event_type": event_type,
            "session_id": "sess-1",
            "timestamp": "2026-09-19T00:00:00Z",
            "context": dict(context),
        }
    )


def _codex_item(event_type: str, item: dict[str, object]) -> str:
    """One raw codex ``item.started`` / ``item.completed`` line."""
    return json.dumps({"type": event_type, "item": item})


@dataclass
class _NeverCancelledWorkspace:
    """Enough workspace for a stream processor: something to interrupt."""

    interrupted: bool = False

    async def interrupt(self) -> bool:
        self.interrupted = True
        return True


@dataclass(frozen=True)
class _Stream:
    """One attempt's worth of raw harness output, and which parser reads it."""

    runner: Runner
    lines: tuple[str, ...]


@dataclass
class _RawStreamHandler:
    """Runs the REAL stream processor over raw lines, into the collector it is given.

    The one thing this double must not do is decide what the stream meant. It
    parses with production's parser and reports production's `StreamResult`, so
    "was there activity" is answered by the code under test rather than by the
    fixture - which is the whole reason these cases are written against raw
    JSONL instead of against `FakeAgentExecutionHandler(uses_tools=...)`.

    The exit code mirrors the real handler's rule closely enough for the retry
    decision: a stream carrying an `error_reason` is a failed phase.
    """

    streams: tuple[_Stream, ...]
    granted_timeouts: list[int] = field(default_factory=list)
    collectors: list[ObservabilityCollector | None] = field(default_factory=list)

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
        runner: Runner = AgentRunner.CLAUDE,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        self.granted_timeouts.append(timeout_seconds)
        self.collectors.append(collector)
        assert collector is not None
        # The LAST entry repeats, so a script of one stream describes an agent
        # that fails the same way however many times it is asked.
        stream = self.streams[min(len(self.granted_timeouts) - 1, len(self.streams) - 1)]
        assert todo.phase_id is not None

        tokens = TokenAccumulator()
        subagents = SubagentTracker()
        processor: EventStreamProcessor | CodexStreamProcessor
        if stream.runner == AgentRunner.CODEX:
            processor = CodexStreamProcessor(
                tokens=tokens,
                collector=collector,
                controller=None,
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                agent_model=agent_model,
                rollout=None,
            )
        else:
            processor = EventStreamProcessor(
                tokens=tokens,
                subagents=subagents,
                observability=None,
                controller=None,
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                workspace_id=None,
                agent_model=agent_model,
                collector=collector,
            )

        stream_result = await processor.process_stream(
            _as_stream(stream.lines), _NeverCancelledWorkspace()
        )
        return AgentExecutionResult(
            stream_result=stream_result,
            tokens=tokens,
            subagents=subagents,
            command=AgentExecutionCompletedCommand(
                execution_id=todo.execution_id,
                phase_id=todo.phase_id,
                session_id=session_id,
                exit_code=1 if stream_result.error_reason else 0,
                last_agent_message=stream_result.last_agent_message,
            ),
        )


# pyright verifies the double still matches the real handler's contract.
_: AgentHandlerProtocol = _RawStreamHandler(streams=())


async def _as_stream(lines: tuple[str, ...]) -> AsyncIterator[str]:
    for line in lines:
        yield line


def _phase(provider: str = AgentProvider.CLAUDE) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="verify",
        name="Verify",
        order=3,
        agent_config=AgentConfiguration(provider=provider, timeout_seconds=1),
        prompt_template="do the thing",
        timeout_seconds=3600,
    )


async def _run_claude(*attempts: _Stream) -> _RawStreamHandler:
    """Drive `run_phase_agent` over claude streams and hand back the handler."""
    return await _run(AgentProvider.CLAUDE, attempts)


async def _run_codex(*attempts: _Stream) -> _RawStreamHandler:
    """Drive `run_phase_agent` over codex streams and hand back the handler."""
    return await _run(AgentProvider.CODEX, attempts)


async def _run(provider: str, attempts: tuple[_Stream, ...]) -> _RawStreamHandler:
    handler = _RawStreamHandler(streams=attempts)
    await run_phase_agent(
        handler=handler,
        todo=TodoItem(
            action=TodoAction.RUN_AGENT,
            execution_id="exec-1",
            phase_id="verify",
            session_id="sess-1",
        ),
        phase=_phase(provider),
        launch=PhaseLaunch(
            workspace=cast("ManagedWorkspace", _NeverCancelledWorkspace()),
            agent_env={},
            claude_cmd=["claude", "-p"],
            started_at=datetime.now(UTC),
            session_manager=await started_session_manager(),
        ),
        session_id="sess-1",
        observability=None,
        retry_policy=NO_WAITING,
    )
    return handler


def _claude(*lines: str) -> _Stream:
    return _Stream(runner=AgentRunner.CLAUDE, lines=lines)


def _codex(*lines: str) -> _Stream:
    return _Stream(runner=AgentRunner.CODEX, lines=lines)


#: A claude stream that finishes cleanly. Second in every script below, so a
#: retry that DID happen would succeed - which is what makes "one attempt" an
#: assertion about the rule rather than about the fixture running out.
CLAUDE_SUCCEEDS = _claude(json.dumps({"type": "result", "is_error": False, "result": "done"}))
CODEX_SUCCEEDS = _codex(
    json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}),
    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
)


class TestActivityOnlyARawStreamCanShow:
    """Each case is a shape the narrow predicate called "nothing happened".

    They share one assertion because they share one consequence: the phase is
    re-run from the top, in the same workspace, over whatever the attempt had
    already done there.
    """

    async def test_a_tool_call_that_arrived_only_as_a_hook_is_activity(self) -> None:
        """Claude reports some tool calls ONLY over the hook channel.

        Those reach `record_hook_event`, which set no witness at all, so a
        phase whose every tool call arrived this way was indistinguishable from
        one that never started - and the `Bash` below would run twice.
        """
        handler = await _run_claude(
            _claude(
                _claude_hook(
                    "tool_execution_started",
                    tool_name="Bash",
                    tool_use_id="tu-1",
                    input_preview="git push",
                ),
                CLAUDE_OVERLOADED_LINE,
            ),
            CLAUDE_SUCCEEDS,
        )

        assert len(handler.granted_timeouts) == 1, (
            "a phase that had already pushed a branch over the hook channel was re-run"
        )

    async def test_a_subagent_that_arrived_only_as_a_hook_is_activity(self) -> None:
        """A whole agent run, started and reported only through hooks.

        The parent `Agent` tool event can be missing or truncated; the
        retained hook events are then the only record that a subagent ran at
        all, and they went to `record_subagent_started`, which set nothing.
        """
        handler = await _run_claude(
            _claude(
                _claude_hook(
                    "tool_execution_started",
                    tool_name="Agent",
                    tool_use_id="tu-sub-1",
                    input_preview="review the diff",
                ),
                CLAUDE_OVERLOADED_LINE,
            ),
            CLAUDE_SUCCEEDS,
        )

        assert len(handler.granted_timeouts) == 1, (
            "a phase that had already run a subagent was re-run, paying for it twice"
        )

    async def test_a_turn_of_only_thinking_is_activity(self) -> None:
        """`thinking` is a content type the loop has no branch for.

        It spends real tokens and it settles what the agent is about to do, so
        an attempt that produced one is not a launch that never started. It set
        neither witness: no `tool_use` block, no `text` block, no message.
        """
        handler = await _run_claude(
            _claude(
                _claude_assistant({"type": "thinking", "thinking": "The failing test is in..."}),
                CLAUDE_OVERLOADED_LINE,
            ),
            CLAUDE_SUCCEEDS,
        )

        assert len(handler.granted_timeouts) == 1, (
            "a turn the model had already paid for was thrown away and bought again"
        )

    async def test_a_content_block_this_parser_has_never_seen_is_activity(self) -> None:
        """The case that cannot be enumerated, which is why the rule is inverted.

        Anthropic ships content types on its own schedule. Whatever the next
        one is, it arrives here as a block with no branch - and the answer has
        to be "the model produced a turn", not "the parser recognised nothing,
        so nothing happened".
        """
        handler = await _run_claude(
            _claude(
                _claude_assistant({"type": "server_tool_use", "name": "web_search"}),
                CLAUDE_OVERLOADED_LINE,
            ),
            CLAUDE_SUCCEEDS,
        )

        assert len(handler.granted_timeouts) == 1, (
            "an unrecognised content block was read as an agent that never started"
        )

    async def test_a_codex_item_that_starts_and_never_completes_is_activity(self) -> None:
        """Codex opens an item when it BEGINS, so a start with no completion is
        the shape of work interrupted mid-flight - the last shape that should
        be re-run.

        `agent_message` records no observation either way, so before the fix
        the started-and-cut-off case left both witnesses false while the
        completed case set `last_agent_message`.
        """
        handler = await _run_codex(
            _codex(
                _codex_item("item.started", {"type": "agent_message", "id": "i-1"}),
                CODEX_AT_CAPACITY_LINE,
            ),
            CODEX_SUCCEEDS,
        )

        assert len(handler.granted_timeouts) == 1, (
            "a codex turn that had started was abandoned and started again"
        )

    async def test_an_unknown_codex_item_type_is_activity(self) -> None:
        """Same argument as the unknown claude block, on the harness that has
        changed its item vocabulary more often.

        A side-effecting item type this parser has never heard of is exactly
        the one whose effects a rerun would repeat.
        """
        handler = await _run_codex(
            _codex(
                _codex_item(
                    "item.started", {"type": "web_search", "id": "i-1", "query": "flaky test"}
                ),
                CODEX_AT_CAPACITY_LINE,
            ),
            CODEX_SUCCEEDS,
        )

        assert len(handler.granted_timeouts) == 1, (
            "an unrecognised codex item type was read as an agent that never started"
        )

    async def test_a_codex_file_change_seen_only_on_completion_is_activity(self) -> None:
        """Some codex versions announce a `file_change` only once it HAS
        happened (#1064), so the completion is the whole record of a workspace
        mutation.

        A regression guard rather than a new case: `record_tool_completed`
        already witnessed this before the predicate was inverted. It is here
        because it is the one case where the evidence arrives strictly after
        the damage, so a future narrowing of the rule would cost edits.
        """
        handler = await _run_codex(
            _codex(
                _codex_item(
                    "item.completed",
                    {"type": "file_change", "id": "i-1", "changes": [{"path": "src/app.py"}]},
                ),
                CODEX_AT_CAPACITY_LINE,
            ),
            CODEX_SUCCEEDS,
        )

        assert len(handler.granted_timeouts) == 1, (
            "a phase that had already edited a file was re-run over its own edit"
        )


class TestTheControlThatKeepsTheRestHonest:
    """Every assertion above is "it did NOT retry", and all of them pass just
    as well on a build that never retries anything - which would silently undo
    #1303 and the $18.63 it was written for. These two are the other
    direction."""

    async def test_a_claude_stream_that_is_busy_before_anything_else_is_retried(self) -> None:
        handler = await _run_claude(_claude(CLAUDE_OVERLOADED_LINE), CLAUDE_SUCCEEDS)

        assert len(handler.granted_timeouts) == 2, (
            "a busy upstream that refused before the model said a word was not retried"
        )

    async def test_a_codex_stream_that_is_busy_before_anything_else_is_retried(self) -> None:
        handler = await _run_codex(_codex(CODEX_AT_CAPACITY_LINE), CODEX_SUCCEEDS)

        assert len(handler.granted_timeouts) == 2, (
            "the exact failure of #1303 - codex at capacity, nothing run yet - was not retried"
        )

    async def test_the_control_streams_really_do_carry_the_busy_fault(self) -> None:
        """Pins the fixtures themselves.

        Every test in this file rests on these two raw lines parsing into the
        two reasons `busy_upstream` accepts by equality. A harness that renamed
        one would turn every "did not retry" assertion above green for the
        wrong reason, and only this test would notice.
        """
        claude = await _run_claude(_claude(CLAUDE_OVERLOADED_LINE))
        codex = await _run_codex(_codex(CODEX_AT_CAPACITY_LINE))

        assert len(claude.granted_timeouts) == NO_WAITING.max_attempts
        assert len(codex.granted_timeouts) == NO_WAITING.max_attempts
        assert CODEX_AT_CAPACITY.endswith(
            "Selected model is at capacity. Please try a different model."
        )
