"""A codex refusal after the agent only READ hands the phase to its fallback (#1825).

#1819 classified the refusal and taught `fallback_attempt` to grant it, and its
tests passed `work_done=False` straight to that method. The run that followed
(exec-dc6a7109b21b, `verify`) still ended failed with no fallback attempt. In
a real verify phase codex reads the PR before it refuses. Every codex item, of
any type, set the "the attempt got somewhere" witness, and that witness was
also the one that refused the fallback. The observed refusal fixture itself
opens with an `agent_message`, so even the stream #1819 pinned was never
granted the fallback.

So each case here is RAW codex JSONL, fed through the real stream processor
into the collector `run_phase_agent` built, ending the way the run did: the
cybersecurity flag on `error` and `turn.failed`, exit code 1. The cases assert
what the execution records: which agent produced the phase's result.

The other side is pinned too. An attempt that may have WRITTEN (a file
change, a command not recognisably read-only) still gets no fallback.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.orchestration import SubagentTracker, TokenAccumulator
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.agent_attempts import (
    run_phase_agent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    EventStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import (
    FallbackLaunch,
    PhaseLaunch,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_1344_raw_stream_activity_stops_a_retry import (
    CLAUDE_SUCCEEDS,
    NO_WAITING,
    _as_stream,
    _claude_assistant,
    _codex,
    _codex_item,
    _NeverCancelledWorkspace,
    _RawStreamHandler,
    _Stream,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_agent_attempts import (
    started_session_manager,
)
from syn_shared.agents import AgentProvider

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )

pytestmark = pytest.mark.unit

_FIXTURE = Path(__file__).parents[6] / "tests" / "fixtures" / "codex" / "codex_turn_failed.jsonl"

#: The observed refusal stream, verbatim: an `agent_message`, then the
#: cybersecurity flag on `error` and again on `turn.failed`.
OBSERVED_REFUSAL: tuple[str, ...] = tuple(_FIXTURE.read_text().splitlines())

#: The refusal's tail alone, without the fixture's leading items.
REFUSAL_TAIL: tuple[str, ...] = tuple(
    line for line in OBSERVED_REFUSAL if json.loads(line)["type"] in {"error", "turn.failed"}
)


def _command(item_id: str, command: str) -> tuple[str, str]:
    """A codex shell command, opened and closed, exactly as codex emits it."""
    item: dict[str, object] = {"id": item_id, "type": "command_execution", "command": command}
    done: dict[str, object] = {**item, "exit_code": 0, "aggregated_output": "..."}
    return _codex_item("item.started", item), _codex_item("item.completed", done)


def _reasoning(item_id: str) -> str:
    return _codex_item("item.completed", {"id": item_id, "type": "reasoning", "text": "hm"})


async def _run_codex_with_claude_fallback(*attempts: _Stream) -> AgentExecutionResult:
    """Drive `run_phase_agent` for a codex verify phase that declared claude/opus."""
    handler = _RawStreamHandler(streams=attempts)
    return await run_phase_agent(
        handler=handler,
        todo=TodoItem(
            action=TodoAction.RUN_AGENT,
            execution_id="exec-1",
            phase_id="verify",
            session_id="sess-1",
        ),
        phase=ExecutablePhase(
            phase_id="verify",
            name="Verify",
            order=3,
            agent_config=AgentConfiguration(
                provider=AgentProvider.CODEX, model="gpt-sol", timeout_seconds=1
            ),
            prompt_template="review the change",
            timeout_seconds=3600,
        ),
        launch=PhaseLaunch(
            workspace=cast("ManagedWorkspace", _NeverCancelledWorkspace()),
            agent_env={},
            claude_cmd=["codex", "exec"],
            started_at=datetime.now(UTC),
            session_manager=await started_session_manager(),
            fallback=FallbackLaunch(
                agent=AgentConfiguration(
                    provider=AgentProvider.CLAUDE, model="opus", timeout_seconds=1
                ),
                agent_env={},
                claude_cmd=["claude", "-p"],
            ),
        ),
        session_id="sess-1",
        observability=None,
        retry_policy=NO_WAITING,
    )


def _producer(result: AgentExecutionResult) -> tuple[str | None, str | None]:
    assert result.command is not None
    return result.command.agent_provider, result.command.agent_model


class TestARefusalAfterOnlyReadingFallsBack:
    """Nothing these attempts did could be duplicated by a run on another agent."""

    @pytest.mark.parametrize(
        "before_refusal",
        [
            pytest.param((), id="the-observed-fixture-as-is"),
            pytest.param(
                (
                    *_command("item_2", "/bin/zsh -lc 'gh pr diff 1819'"),
                    *_command("item_3", "/bin/zsh -lc 'sed -n 1,200p agent_attempts.py'"),
                    *_command("item_4", "/bin/zsh -lc 'rg -n fallback_attempt packages | head'"),
                    _reasoning("item_5"),
                ),
                id="read-only-commands-and-reasoning",
            ),
        ],
    )
    async def test_the_claude_fallback_runs_and_the_result_names_it(
        self, before_refusal: tuple[str, ...]
    ) -> None:
        primary = _codex(*before_refusal, *OBSERVED_REFUSAL)

        result = await _run_codex_with_claude_fallback(primary, CLAUDE_SUCCEEDS)

        assert result.exit_code == 0
        assert _producer(result) == (AgentProvider.CLAUDE, "opus")


class TestARefusalAfterAPossibleWriteDoesNot:
    """A rerun on another agent would redo what these attempts may have done."""

    @pytest.mark.parametrize(
        "before_refusal",
        [
            pytest.param(
                (
                    _codex_item(
                        "item.completed",
                        {
                            "id": "item_2",
                            "type": "file_change",
                            "status": "completed",
                            "changes": [{"path": "a.py", "kind": "update"}],
                        },
                    ),
                ),
                id="file-change",
            ),
            pytest.param(_command("item_2", "/bin/zsh -lc 'git push origin HEAD'"), id="push"),
            pytest.param(
                _command("item_2", "/bin/zsh -lc 'cat a.py > b.py'"), id="read-redirected"
            ),
            pytest.param(
                (_codex_item("item.started", {"id": "item_2", "type": "mcp_tool_call"}),),
                id="an-item-type-nobody-taught-it",
            ),
        ],
    )
    async def test_the_primary_failure_is_the_phase_result(
        self, before_refusal: tuple[str, ...]
    ) -> None:
        primary = _codex(*before_refusal, *REFUSAL_TAIL)

        result = await _run_codex_with_claude_fallback(primary, CLAUDE_SUCCEEDS)

        assert result.exit_code == 1
        assert _producer(result) == (AgentProvider.CODEX, "gpt-sol")
        assert "flagged for possible cybersecurity risk" in str(result.stream_result.error_reason)


class TestTheClaudeParserDrawsTheSameLine:
    """The claude processor feeds the same witness, from its own stream shapes."""

    @pytest.mark.parametrize(
        ("content", "wrote"),
        [
            ([{"type": "thinking", "thinking": "hm"}, {"type": "text", "text": "reading"}], False),
            (
                [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "a"}}],
                False,
            ),
            (
                [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat a"}}],
                False,
            ),
            ([{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "a"}}], True),
            (
                [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Bash",
                        "input": {"command": "git push"},
                    }
                ],
                True,
            ),
            ([{"type": "server_tool_use", "id": "t1"}], True),
        ],
    )
    async def test_claude_content(self, content: list[dict[str, object]], wrote: bool) -> None:
        collector = ObservabilityCollector(
            writer=None,
            session_id="s",
            execution_id="e",
            phase_id="verify",
            workspace_id=None,
            requested_model=None,
        )
        processor = EventStreamProcessor(
            tokens=TokenAccumulator(),
            subagents=SubagentTracker(),
            observability=None,
            controller=None,
            execution_id="e",
            phase_id="verify",
            session_id="s",
            workspace_id=None,
            agent_model=None,
            collector=collector,
        )

        await processor.process_stream(
            _as_stream((_claude_assistant(*content),)), _NeverCancelledWorkspace()
        )

        assert collector.saw_agent_activity
        assert collector.may_have_written is wrote
