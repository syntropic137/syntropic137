"""The decisions `_run_headless` delegates to its helpers (#1144).

`_record_session_summary` decides WHO writes a phase's Lane 2 summary: the
handler for claude, CodexStreamProcessor for codex, nobody without a collector.
`_assemble_result` decides whether a run gets a completion command: only when
an exit status was observed (#1341). Each is pinned at the value it emits, with
fixture numbers no default could produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ReviewVerdict,
    SideEffectStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    FinalUsage,
    _assemble_result,
    _record_session_summary,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import (
    AgentVerdict,
    VerdictStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.SubagentTracker import (
    SubagentTracker,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)
from syn_shared.agents import AgentRunner

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )

pytestmark = pytest.mark.unit

_USAGE = FinalUsage(
    input_tokens=41_017,
    output_tokens=2_309,
    cache_creation=777,
    cache_read=9_131,
    is_authoritative=False,
)


def _stream_result() -> StreamResult:
    return StreamResult(
        line_count=57,
        interrupt_requested=False,
        interrupt_reason=None,
        verdict=AgentVerdict(
            status=VerdictStatus.SUCCESS,
            reported_side_effects=SideEffectStatus.DENIED,
            reported_review_verdict=ReviewVerdict.CERTIFIED,
        ),
        total_cost_usd=None,
        duration_ms=123_456,
        num_turns=17,
        last_agent_message="the last thing the agent said",
    )


@dataclass(frozen=True)
class _Summary:
    total_cost_usd: float | None
    input_tokens: int
    output_tokens: int
    cache_creation: int
    cache_read: int
    num_turns: int | None
    duration_ms: int | None
    totals_are_authoritative: bool


class _SummaryRecorder:
    """Stands in for the collector; records only the call under test."""

    def __init__(self) -> None:
        self.summaries: list[_Summary] = []

    async def record_session_summary(
        self,
        total_cost_usd: float | None,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int,
        cache_read: int,
        num_turns: int | None,
        duration_ms: int | None,
        totals_are_authoritative: bool = True,
    ) -> None:
        self.summaries.append(
            _Summary(
                total_cost_usd=total_cost_usd,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation=cache_creation,
                cache_read=cache_read,
                num_turns=num_turns,
                duration_ms=duration_ms,
                totals_are_authoritative=totals_are_authoritative,
            )
        )


def _collector(recorder: _SummaryRecorder) -> ObservabilityCollector:
    # The helper calls exactly one method, which the recorder provides.
    return cast("ObservabilityCollector", recorder)


class TestRecordSessionSummary:
    async def test_a_claude_phase_records_its_final_usage(self) -> None:
        recorder = _SummaryRecorder()

        await _record_session_summary(
            _collector(recorder), AgentRunner.CLAUDE, _stream_result(), _USAGE
        )

        assert recorder.summaries == [
            _Summary(
                total_cost_usd=None,
                input_tokens=41_017,
                output_tokens=2_309,
                cache_creation=777,
                cache_read=9_131,
                num_turns=17,
                duration_ms=123_456,
                totals_are_authoritative=False,
            )
        ]

    async def test_a_codex_phase_leaves_its_summary_to_the_codex_processor(self) -> None:
        recorder = _SummaryRecorder()

        await _record_session_summary(
            _collector(recorder), AgentRunner.CODEX, _stream_result(), _USAGE
        )

        assert recorder.summaries == []

    async def test_no_collector_records_nothing_and_does_not_fail(self) -> None:
        await _record_session_summary(None, AgentRunner.CLAUDE, _stream_result(), _USAGE)


class TestAssembleResult:
    def test_an_observed_exit_becomes_a_command_carrying_usage_and_verdict(self) -> None:
        result = _assemble_result(
            todo=TodoItem(
                execution_id="exec-1144", action=TodoAction.RUN_AGENT, phase_id="implement"
            ),
            session_id="sess-1144",
            exit_code=3,
            stream_result=_stream_result(),
            usage=_USAGE,
            tokens=TokenAccumulator(),
            subagents=SubagentTracker(),
            launch_failed=True,
        )

        command = result.command
        assert command is not None
        assert (command.aggregate_id, command.phase_id, command.session_id) == (
            "exec-1144",
            "implement",
            "sess-1144",
        )
        assert command.exit_code == 3
        assert result.exit_code == 3
        assert (
            command.input_tokens,
            command.output_tokens,
            command.cache_creation_tokens,
            command.cache_read_tokens,
        ) == (41_017, 2_309, 777, 9_131)
        assert command.last_agent_message == "the last thing the agent said"
        assert command.reported_side_effects == SideEffectStatus.DENIED
        assert command.reported_review_verdict == ReviewVerdict.CERTIFIED
        assert result.usage is _USAGE
        assert result.launch_failed is True

    def test_a_cancelled_run_gets_no_command_but_keeps_its_usage(self) -> None:
        result = _assemble_result(
            todo=TodoItem(
                execution_id="exec-1144", action=TodoAction.RUN_AGENT, phase_id="implement"
            ),
            session_id="sess-1144",
            exit_code=None,
            stream_result=_stream_result(),
            usage=_USAGE,
            tokens=TokenAccumulator(),
            subagents=SubagentTracker(),
            launch_failed=True,
        )

        assert result.command is None
        assert result.exit_code is None
        assert result.usage is _USAGE
        assert result.launch_failed is True
