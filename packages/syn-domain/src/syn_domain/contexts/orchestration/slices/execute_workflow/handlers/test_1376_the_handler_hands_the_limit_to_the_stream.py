"""#1376: the cost limit the phase was given reaches the stream that enforces it.

The stream processors stop an agent that spends past its limit, and the
processor hands the limit to `AgentExecutionHandler.handle`. The hop between
them - `_select_stream_processor` building the processor WITH the limit - is
what these pin. Every other test stops on one side of it: the stream tests
construct a processor directly, and the processor tests stop at a fake
handler. Deleting the keyword in either branch left all of them green while
real phases ran with no limit at all.

So these run the REAL handler over a scripted workspace, for both runners.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_cost_limit import (
    PhaseCostLimit,
)
from syn_shared.agents import AgentRunner, ModelId

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
        AgentExecutionResult,
    )

pytestmark = pytest.mark.unit

_CLAUDE_MODEL = ModelId.CLAUDE_OPUS_5_5.value
_CODEX_MODEL = "gpt-5.6"
#: Far below what one turn of either stream below costs at any listed rate.
_LIMIT_USD = 0.01


class _ScriptedWorkspace:
    """A workspace whose agent emits ``lines``, and which records being interrupted."""

    id = "ws-1376"
    last_stream_exit_code = 0

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.interrupted = False

    def stream(self, *_args: object, **_kwargs: object) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for line in self._lines:
                yield line

        return gen()

    async def interrupt(self) -> bool:
        self.interrupted = True
        return True

    async def collect_files(self, **_kwargs: object) -> list[tuple[str, bytes]]:
        return []

    def keep_git_credential_fresh(self, **_kwargs: object) -> contextlib.nullcontext[None]:
        return contextlib.nullcontext()


class _Collector:
    """The collector surface both stream processors call, recording nothing."""

    def note_agent_activity(self, *, changed_nothing: bool = False) -> None:
        return

    def note_observed_model(self, model: str | None) -> None:
        return

    async def record_token_usage(self, *_args: object, **_kwargs: object) -> None:
        return

    async def record_session_summary(self, **_kwargs: object) -> None:
        return

    async def record_tool_started(self, **_kwargs: object) -> None:
        return

    async def record_tool_completed(self, **_kwargs: object) -> None:
        return

    def __getattr__(self, name: str) -> object:
        # Any other recording the stream makes is irrelevant to the limit.
        async def ignore(*_args: object, **_kwargs: object) -> None:
            return

        return ignore


def _claude_turn(message_id: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": message_id,
                "model": _CLAUDE_MODEL,
                "content": [{"type": "text", "text": "working"}],
                "usage": {"input_tokens": 2_000_000, "output_tokens": 0},
            },
        }
    )


def _codex_turn() -> list[str]:
    return [
        '{"type":"turn.started"}',
        json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 2_000_000, "output_tokens": 0}}
        ),
    ]


async def _run(
    runner: AgentRunner, lines: list[str], model: str, cost_limit: PhaseCostLimit | None
) -> tuple[AgentExecutionResult, _ScriptedWorkspace]:
    workspace = _ScriptedWorkspace(lines)
    result = await AgentExecutionHandler(controller=None).handle(
        todo=TodoItem(execution_id="exec-1376", action=TodoAction.RUN_AGENT, phase_id="experiment"),
        workspace=workspace,  # type: ignore[arg-type]
        agent_env={},
        claude_cmd=["agent"],
        session_id="session-1376",
        agent_model=model,
        timeout_seconds=3600,
        collector=_Collector(),  # type: ignore[arg-type]
        runner=runner,
        cost_limit=cost_limit,
    )
    return result, workspace


_CASES = [
    pytest.param(
        AgentRunner.CLAUDE,
        [_claude_turn("m1"), _claude_turn("m2"), _claude_turn("m3")],
        _CLAUDE_MODEL,
        id="claude",
    ),
    pytest.param(AgentRunner.CODEX, _codex_turn() * 3, _CODEX_MODEL, id="codex"),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("runner", "lines", "model"), _CASES)
async def test_the_handler_stops_a_phase_that_spends_past_its_limit(
    runner: AgentRunner, lines: list[str], model: str
) -> None:
    result, workspace = await _run(runner, lines, model, PhaseCostLimit(_LIMIT_USD))

    assert workspace.interrupted, f"the {runner} stream was never given the phase's limit"
    reason = result.stream_result.cost_limit_reason
    assert reason is not None
    assert reason.startswith(f"cost limit USD {_LIMIT_USD:.2f} exceeded at USD ")
    assert result.stream_result.line_count < len(lines), "the stream must stop at the crossing"


@pytest.mark.anyio
@pytest.mark.parametrize(("runner", "lines", "model"), _CASES)
async def test_the_handler_leaves_a_phase_with_no_limit_running(
    runner: AgentRunner, lines: list[str], model: str
) -> None:
    result, workspace = await _run(runner, lines, model, None)

    assert not workspace.interrupted
    assert result.stream_result.cost_limit_reason is None
