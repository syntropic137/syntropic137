"""The model stamped on an artifact is the one the harness ANNOUNCED (#1284).

A cross-model review proves nothing unless the record names the models that ran,
and the tempting value to record is the one the phase asked for: it is already
in `agent_config`, it is in scope at collection time, and it is right most of
the time. It is also not an observation. A codex phase ignores a forwarded
claude model entirely, and a delegated sub-agent may run on a different model
than its parent - so "requested" written under the name "ran" would read as
evidence in exactly the cases where there is none, which is worse than the field
being absent.

So the processor below is constructed with a REQUESTED model and fed a stream
announcing a different one, and every assertion is about which of the two comes
out. The requested value never does, including when the stream says nothing at
all.
"""

from __future__ import annotations

import json

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    AgentExecutionCompletedCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_event_stream_processor import (
    MockWorkspace,
    _lines_to_stream,
    _make_processor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

pytestmark = pytest.mark.unit

#: What `_make_processor` passes as `agent_model` — the value the phase asked
#: for. Nothing in this file may ever produce it.
REQUESTED = "claude-sonnet"
ANNOUNCED = "claude-sonnet-4-5-20250929"
LATER = "claude-haiku-4-5-20251001"


def _system_line(model: object) -> str:
    return json.dumps({"type": "system", "subtype": "init", "model": model})


def _assistant_line(model: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"model": model, "content": [{"type": "text", "text": "working"}]},
        }
    )


class TestTheStreamIsTheOnlySourceOfTheModel:
    async def test_the_announced_model_is_reported_not_the_requested_one(self) -> None:
        proc = _make_processor()
        result = await proc.process_stream(
            _lines_to_stream(_system_line(ANNOUNCED)), MockWorkspace()
        )
        assert result.announced_model == ANNOUNCED
        assert result.announced_model != REQUESTED

    async def test_an_assistant_line_announces_it_too(self) -> None:
        """A recording that begins after the init line still yields an answer;
        claude repeats the model under `message` on every assistant line."""
        proc = _make_processor()
        result = await proc.process_stream(
            _lines_to_stream(_assistant_line(ANNOUNCED)), MockWorkspace()
        )
        assert result.announced_model == ANNOUNCED

    async def test_the_first_announcement_wins(self) -> None:
        """Last-wins would let anything that ever put another agent's line on
        this stream rebind the identity at the end of the run - the same hazard
        the leader session id capture is first-wins for (#895)."""
        proc = _make_processor()
        result = await proc.process_stream(
            _lines_to_stream(_system_line(ANNOUNCED), _assistant_line(LATER)),
            MockWorkspace(),
        )
        assert result.announced_model == ANNOUNCED

    async def test_a_codex_stream_announces_nothing(self) -> None:
        """Codex's stream carries no model at all, which is why its cost goes
        unpriced rather than guessed (#788). The requested model must not be
        substituted here: it would report every codex phase as having run a
        claude model, and the pricing precedent says guessing is the worse
        failure.
        """
        proc = _make_processor()
        result = await proc.process_stream(
            _lines_to_stream(
                json.dumps({"type": "thread.started", "thread_id": "01a04903-c2f9-7de3"}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12}}),
            ),
            MockWorkspace(),
        )
        assert result.announced_model is None

    async def test_an_empty_stream_announces_nothing(self) -> None:
        proc = _make_processor()
        result = await proc.process_stream(_lines_to_stream(), MockWorkspace())
        assert result.announced_model is None

    @pytest.mark.parametrize("blank", ["", "   ", None, 4])
    async def test_a_line_that_says_nothing_usable_is_not_taken(self, blank: object) -> None:
        """A blank or non-string would be recorded as a model that ran, and
        rendering it is how "" ends up looking like a real answer."""
        proc = _make_processor()
        result = await proc.process_stream(_lines_to_stream(_system_line(blank)), MockWorkspace())
        assert result.announced_model is None


def _runtime() -> PhaseRuntime:
    return PhaseRuntime(capture_port=None, session_store=None, writer=None, ledger=None)


def _run(announced_model: str | None) -> AgentExecutionResult:
    from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
        StreamResult,
    )

    return AgentExecutionResult(
        stream_result=StreamResult(
            line_count=1,
            interrupt_requested=False,
            interrupt_reason=None,
            agent_task_result=None,
            announced_model=announced_model,
        ),
        tokens=TokenAccumulator(),
        subagents=SubagentTracker(),
        command=AgentExecutionCompletedCommand(
            execution_id="exec-1", phase_id="verify", session_id="sess-1"
        ),
    )


class TestTheRuntimeHandsBackWhoRan:
    """The runtime holds the announcement because the stream is gone by the
    time artifacts are collected - the two happen in different handlers.
    """

    def test_the_provider_is_the_caller_s_and_the_model_is_the_stream_s(self) -> None:
        """Two different KINDS of fact in one value: we CHOSE the provider, so
        there is no observation to make; only the stream ever said the model."""
        runtime = _runtime()
        runtime.record_agent_run("verify", _run(ANNOUNCED))
        agent = runtime.agent_for("verify", provider="claude")
        assert (agent.provider, agent.model) == ("claude", ANNOUNCED)

    def test_a_phase_that_announced_nothing_yields_a_provider_and_no_model(self) -> None:
        """The codex case. The provider alone still proves WHICH HARNESS ran,
        which is most of what a cross-model claim needs; the model stays absent
        rather than being filled in from configuration.
        """
        runtime = _runtime()
        runtime.record_agent_run("verify", _run(None))
        agent = runtime.agent_for("verify", provider="codex")
        assert (agent.provider, agent.model) == ("codex", None)

    def test_one_phase_s_announcement_is_not_read_for_another(self) -> None:
        runtime = _runtime()
        runtime.record_agent_run("investigate", _run(ANNOUNCED))
        assert runtime.agent_for("report", provider="claude").model is None

    def test_a_phase_that_never_ran_an_agent_has_no_model(self) -> None:
        assert _runtime().agent_for("verify", provider="claude").model is None
