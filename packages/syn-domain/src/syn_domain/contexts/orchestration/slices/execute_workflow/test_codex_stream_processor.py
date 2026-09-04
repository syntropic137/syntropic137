"""Tests for CodexStreamProcessor.

Uses the golden real-captured fixture
(``packages/syn-domain/tests/fixtures/codex/codex_exec_recording.jsonl``),
plus two hand-crafted failure fixtures. The golden fixture is a SINGLE-turn
recording (one ``turn.completed``); no real multi-turn ``codex exec --json``
capture was available in this environment, so cross-turn summation is not
exercised end-to-end here. If a real multi-turn recording becomes available,
add a ``test_multi_turn_sums_across_turns`` case that asserts summed totals
equal the sum of each turn's fresh_input/output/cache_read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

from syn_domain.contexts.orchestration.slices.execute_workflow.CodexStreamProcessor import (
    MISSING_TERMINAL_TURN_REASON,
    CodexStreamProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)

_FIXTURES_DIR = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "codex"


@dataclass
class _RecordingCollector:
    calls: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)

    async def record_tool_started(self, **kwargs: object) -> None:
        self.calls.append(("tool_started", kwargs))

    async def record_tool_completed(self, **kwargs: object) -> None:
        self.calls.append(("tool_completed", kwargs))

    async def record_token_usage(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("token_usage", {"args": args, **kwargs}))

    async def record_session_summary(self, **kwargs: object) -> None:
        self.calls.append(("summary", kwargs))


class _NoopWorkspace:
    last_stream_exit_code = 0

    async def interrupt(self) -> bool:
        return True


async def _lines(path: Path) -> AsyncIterator[str]:
    for line in path.read_text().splitlines():
        yield line


def _is_json(line: str) -> bool:
    try:
        json.loads(line)
    except json.JSONDecodeError:
        return False
    return True


def _make_processor(
    collector: _RecordingCollector, agent_model: str | None = "gpt-5.6"
) -> tuple[CodexStreamProcessor, TokenAccumulator]:
    tokens = TokenAccumulator()
    processor = CodexStreamProcessor(
        tokens=tokens,
        collector=collector,
        controller=None,
        execution_id="exec-1",
        phase_id="p1",
        session_id="s1",
        agent_model=agent_model,
    )
    return processor, tokens


@pytest.mark.asyncio
async def test_codex_recording_produces_timeline() -> None:
    rec = _FIXTURES_DIR / "codex_exec_recording.jsonl"
    collector = _RecordingCollector()
    processor, tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    kinds = [c[0] for c in collector.calls]
    assert "tool_started" in kinds
    assert "tool_completed" in kinds
    assert "token_usage" in kinds

    summary = next(c[1] for c in collector.calls if c[0] == "summary")
    assert summary["input_tokens"] > 0
    assert summary["output_tokens"] > 0
    assert summary["total_cost_usd"] is not None
    assert summary["total_cost_usd"] > 0

    # Fixture: input_tokens=97006, cached_input_tokens=87808, output_tokens=288,
    # reasoning_output_tokens=0 => fresh_input=9198, cache_read=87808, output=288.
    assert result.reported_usage is not None
    assert result.reported_usage.input_tokens == 9198
    assert result.reported_usage.cache_read == 87808
    assert result.reported_usage.output_tokens == 288
    assert result.num_turns == 1
    assert result.error_reason is None

    # Shared TokenAccumulator updated too (not just StreamResult.reported_usage).
    assert tokens.input_tokens == result.reported_usage.input_tokens
    assert tokens.output_tokens == result.reported_usage.output_tokens
    assert tokens.cache_read_tokens == result.reported_usage.cache_read

    # Raw provider-native JSONL preserved, including interleaved non-JSON
    # noise lines the real codex CLI emits on stdout.
    assert result.conversation_lines
    assert any("turn.completed" in line for line in result.conversation_lines)


@pytest.mark.asyncio
async def test_command_execution_tool_pair_recorded() -> None:
    rec = _FIXTURES_DIR / "codex_exec_recording.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    await processor.process_stream(_lines(rec), _NoopWorkspace())

    started = [c[1] for c in collector.calls if c[0] == "tool_started"]
    completed = [c[1] for c in collector.calls if c[0] == "tool_completed"]

    bash_started = [c for c in started if c["tool_name"] == "Bash"]
    bash_completed = [c for c in completed if c["tool_name"] == "Bash"]
    assert len(bash_started) == 2  # item_2 ('cat one.txt'), item_4 ('ls -1')
    assert len(bash_completed) == 2
    assert all(c["success"] is True for c in bash_completed)
    assert bash_started[0]["input_preview"] == "/bin/zsh -lc 'cat one.txt'"
    assert bash_completed[0]["output_preview"] == "alpha\n"

    edit_started = [c for c in started if c["tool_name"] == "Edit"]
    edit_completed = [c for c in completed if c["tool_name"] == "Edit"]
    assert len(edit_started) == 2  # item_1 (one.txt), item_3 (two.txt)
    assert len(edit_completed) == 2
    assert all(c["success"] is True for c in edit_completed)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_truncated_line_the_stream_recovers_from_is_not_a_failure() -> None:
    """The fixture is a half-written `turn.completed`, then a complete one.

    Before #1146 the truncated line failed the phase on sight. It is now a
    candidate reason, and the terminal turn that follows settles the run as the
    success it was - the usage on that second line is authoritative and gets
    reported.
    """
    rec = _FIXTURES_DIR / "codex_malformed.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.error_reason is None
    assert result.num_turns == 1
    assert result.reported_usage is not None
    assert result.reported_usage.input_tokens == 100


@pytest.mark.asyncio
async def test_no_terminal_usage_fails_explicitly() -> None:
    rec = _FIXTURES_DIR / "codex_no_terminal.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.error_reason is not None
    assert "turn.completed" in result.error_reason
    assert result.num_turns == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_truncated_codex_stream_reports_no_harness_totals() -> None:
    """A cut-off codex run has an accumulator, not a report (#1164).

    `StreamResult.reported_usage` is what `FinalUsage.resolve` reads to decide
    whether the numbers are the harness's own, and codex fills the same field
    the claude parser does. Left populated, a truncated run's partial sum would
    be labelled authoritative on the way to the aggregate - the same
    presence-vs-magnitude confusion, one processor over.
    """
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    truncated = await processor.process_stream(
        _lines(_FIXTURES_DIR / "codex_no_terminal.jsonl"), _NoopWorkspace()
    )
    assert truncated.reported_usage is None

    # And the complete run over the same processor DOES report - otherwise the
    # assertion above would hold for a field nothing ever sets.
    complete_processor, _ = _make_processor(_RecordingCollector())
    complete = await complete_processor.process_stream(
        _lines(_FIXTURES_DIR / "codex_exec_recording.jsonl"), _NoopWorkspace()
    )
    assert complete.reported_usage is not None


@pytest.mark.asyncio
async def test_empty_stream_fails_explicitly() -> None:
    async def _empty() -> AsyncIterator[str]:
        return
        yield  # pragma: no cover - makes this an async generator

    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_empty(), _NoopWorkspace())

    assert result.error_reason is not None
    assert result.line_count == 0
    # A session summary is still emitted exactly once (single-layer emission
    # guarantee), just with zeroed totals and cost unavailable if the model
    # can't be priced from zero tokens... it CAN be priced (0 * rate == 0),
    # so total_cost_usd is 0.0 for a known model on an empty stream.
    summaries = [c for c in collector.calls if c[0] == "summary"]
    assert len(summaries) == 1


@pytest.mark.asyncio
async def test_unknown_model_marks_cost_unavailable() -> None:
    rec = _FIXTURES_DIR / "codex_exec_recording.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector, agent_model="mystery-model")

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.total_cost_usd is None
    summary = next(c[1] for c in collector.calls if c[0] == "summary")
    assert summary["total_cost_usd"] is None


@pytest.mark.asyncio
async def test_none_model_marks_cost_unavailable_not_haiku_not_gpt_5_6() -> None:
    """A codex phase with no explicit model (agent_model=None) must NOT be
    priced at all - specifically not claude haiku rates (the original #788
    bug) and not GPT-5.6 rates (the #788 fix's over-correction, which
    synthesized "codex" as the model and let it alias to gpt-5.6 pricing).
    Cost must resolve to unknown/unpriced (None).
    """
    rec = _FIXTURES_DIR / "codex_exec_recording.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector, agent_model=None)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.total_cost_usd is None
    summary = next(c[1] for c in collector.calls if c[0] == "summary")
    assert summary["total_cost_usd"] is None


@pytest.mark.asyncio
async def test_cancel_signal_interrupts() -> None:
    from syn_adapters.control.commands import ControlSignalType

    class _SpyWorkspace:
        last_stream_exit_code = 0

        def __init__(self) -> None:
            self.interrupted = False

        async def interrupt(self) -> bool:
            self.interrupted = True
            return True

    class _Signal:
        signal_type = ControlSignalType.CANCEL
        reason = "user requested stop"

    class _FakeController:
        async def check_signal(self, execution_id: str) -> _Signal:
            return _Signal()

    async def _many_lines() -> AsyncIterator[str]:
        for _ in range(11):
            yield '{"type":"turn.started"}'

    collector = _RecordingCollector()
    tokens = TokenAccumulator()
    processor = CodexStreamProcessor(
        tokens=tokens,
        collector=collector,
        controller=_FakeController(),  # type: ignore[arg-type]
        execution_id="exec-1",
        phase_id="p1",
        session_id="s1",
        agent_model="gpt-5.6",
    )
    workspace = _SpyWorkspace()

    result = await processor.process_stream(_many_lines(), workspace)

    assert workspace.interrupted is True
    assert result.interrupt_requested is True
    assert result.interrupt_reason == "user requested stop"


@pytest.mark.asyncio
async def test_cancel_with_no_reason_still_interrupts() -> None:
    """#918: a cancel with no reason text is still a cancel, codex side.

    ``test_cancel_signal_interrupts`` above sends ``reason="user requested
    stop"`` and passes both before and after the fix, because
    ``interrupt_requested`` used to be derived as ``interrupt_reason is not
    None``. The default CLI path - ``syn control cancel <id> --force`` with no
    ``-r`` - sends no reason at all, so the flag evaluated False and the
    workflow continued to its remaining phases.
    """
    from syn_shared.control import ControlSignalType

    class _SpyWorkspace:
        last_stream_exit_code = 0

        def __init__(self) -> None:
            self.interrupted = False

        async def interrupt(self) -> bool:
            self.interrupted = True
            return True

    class _Signal:
        signal_type = ControlSignalType.CANCEL
        reason = None  # what the CLI actually sends without -r

    class _FakeController:
        async def check_signal(self, execution_id: str) -> _Signal:
            return _Signal()

    async def _many_lines() -> AsyncIterator[str]:
        for _ in range(11):
            yield '{"type":"turn.started"}'

    processor = CodexStreamProcessor(
        tokens=TokenAccumulator(),
        collector=_RecordingCollector(),
        controller=_FakeController(),  # type: ignore[arg-type]
        execution_id="exec-1",
        phase_id="p1",
        session_id="s1",
        agent_model="gpt-5.6",
    )
    workspace = _SpyWorkspace()

    result = await processor.process_stream(_many_lines(), workspace)

    assert workspace.interrupted is True
    assert result.interrupt_requested is True, (
        "a cancel without a reason must still request interrupt (#918)"
    )
    assert result.interrupt_reason is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turn_failed_reports_what_codex_said_not_the_missing_turn() -> None:
    """Recorded from production (#1116).

    A `verify` phase died and the platform reported "codex stream ended without
    a terminal turn.completed event" while the stream's own last two lines said
    the prompt had been refused by a content classifier. True, and unactionable:
    it names the symptom and hides the cause. The fixture is that exact tail.
    """
    rec = _FIXTURES_DIR / "codex_turn_failed.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.error_reason is not None
    assert "flagged for possible cybersecurity risk" in result.error_reason
    assert "without a terminal turn.completed" not in result.error_reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turn_failed_reason_is_read_from_the_nested_error_too() -> None:
    """A stream can end on `turn.failed` alone, with no preceding `error` line.

    The two events spell the message differently - top-level `message` versus
    `error.message` - so a parser that reads only the shape it happened to see
    first still fails silently on the other.
    """
    rec = _FIXTURES_DIR / "codex_turn_failed_nested_only.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.error_reason is not None
    assert "stream disconnected before completion" in result.error_reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_recovered_turn_is_not_failed_by_the_hiccup_it_recovered_from() -> None:
    """An `error` the CLI recovers from must not fail a phase that finished.

    `AgentExecutionHandler` forces a non-zero phase exit whenever a codex stream
    carries ANY `error_reason`, without consulting `saw_terminal_turn`. So a
    reason latched mid-turn would fail a clean run and report the hiccup as its
    cause - inventing a failure rather than masking one. This module's own
    comment already names that class as the worse defect.

    Found by the cross-model review of #1117.
    """
    rec = _FIXTURES_DIR / "codex_error_then_recovered.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.error_reason is None
    assert result.num_turns == 1


# --- #1146: a `{`-leading line the AGENT echoed is not a protocol fault ------
#
# stdout carries the agent's own subprocess output alongside the codex event
# stream (ADR-043), so `startswith("{")` cannot mean "this was meant to be an
# event". These four tests drive the real processor over fixtures whose junk
# lines are the shapes this repository actually contains.

#: The line that failed `exec-678b083e0259` (a rework of dashboard PR #1071),
#: verbatim from issue #1146. It is TSX from the repo under review, echoed to
#: stdout while the agent read the file it had been asked to verify.
_ECHOED_TSX_LINE = (
    "{tokens.settled ? formatTokens(tokens.total) : `${formatTokens(tokens.total)} so far`}"
)


def _observable(calls: list[tuple[str, Mapping[str, object]]]) -> list[object]:
    """The parts of a collector transcript a stream's CONTENT determines.

    `duration_ms` is wall-clock and differs between two runs of identical
    input, so it is dropped; everything else must match exactly.
    """
    return [
        (kind, {k: v for k, v in kwargs.items() if k != "duration_ms"}) for kind, kwargs in calls
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_tsx_line_from_1146_does_not_fail_a_stream_that_completes() -> None:
    """The exact reported line, in a run that reaches `turn.completed`.

    This is the whole bug: the phase died on a line of someone else's TSX. The
    run must succeed, and it must succeed with its authoritative usage intact -
    a phase that "passes" having lost its token totals is not a fix.
    """
    rec = _FIXTURES_DIR / "codex_brace_echo_noisy.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    # The line really was on this stream - not a fixture that quietly omits it.
    assert _ECHOED_TSX_LINE in [line.strip() for line in result.conversation_lines]

    assert result.error_reason is None, (
        f"a line of TSX the agent echoed failed the phase: {result.error_reason}"
    )
    assert result.num_turns == 1
    assert result.reported_usage is not None
    assert result.reported_usage.input_tokens == 10168  # 103168 fresh - 93000 cached
    assert result.reported_usage.output_tokens == 10020


@pytest.mark.unit
@pytest.mark.asyncio
async def test_every_brace_leading_shape_this_repo_contains_is_survivable() -> None:
    """One echoed shape passing is luck; the set passing is the property.

    JSX/TSX interpolation, a JSX comment expression, JSON-with-comments, a
    handlebars/jinja expression, a jinja statement, a jq filter and a python
    dict from a traceback - seven lines, all `{`-leading, none of them valid
    JSON, all of them ordinary content in this repository.
    """
    rec = _FIXTURES_DIR / "codex_brace_echo_noisy.jsonl"
    raw = rec.read_text().splitlines()
    unparseable = [line for line in raw if line.startswith("{") and not _is_json(line)]
    assert len(unparseable) == 7, "fixture no longer carries the shapes under test"
    assert "{{ value }}" in unparseable  # handlebars / jinja
    assert any(line.startswith("{ ") and "//" in line for line in unparseable)  # JSONC
    assert any("formatTokens" in line for line in unparseable)  # TSX

    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.error_reason is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_echoed_lines_change_nothing_about_how_real_events_are_handled() -> None:
    """Equivalence: the same events, with and without the echoed lines.

    The risk in loosening a parser is that it starts dropping real events too.
    Rather than re-asserting the timeline by hand, this runs a clean stream and
    a stream carrying the SAME events plus seven echoed lines, and requires the
    two transcripts to be indistinguishable - every tool op, every token
    figure, every turn.
    """
    clean_collector = _RecordingCollector()
    clean_processor, clean_tokens = _make_processor(clean_collector)
    clean = await clean_processor.process_stream(
        _lines(_FIXTURES_DIR / "codex_brace_echo_clean.jsonl"), _NoopWorkspace()
    )

    noisy_collector = _RecordingCollector()
    noisy_processor, noisy_tokens = _make_processor(noisy_collector)
    noisy = await noisy_processor.process_stream(
        _lines(_FIXTURES_DIR / "codex_brace_echo_noisy.jsonl"), _NoopWorkspace()
    )

    assert noisy.line_count == clean.line_count + 7  # the junk WAS read
    assert _observable(noisy_collector.calls) == _observable(clean_collector.calls)
    assert noisy.reported_usage == clean.reported_usage
    assert noisy.num_turns == clean.num_turns
    assert noisy.error_reason == clean.error_reason is None
    assert noisy.leader_native_session_id == clean.leader_native_session_id
    assert (noisy_tokens.input_tokens, noisy_tokens.output_tokens) == (
        clean_tokens.input_tokens,
        clean_tokens.output_tokens,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_an_echoed_line_on_a_stream_that_never_completes_still_reports() -> None:
    """A cut-off stream still fails, and names the line it was cut off on.

    The fixture echoes the TSX line early and is then truncated mid-event. Both
    lines are `{`-leading and unparseable, so this pins TWO decisions: that the
    parse candidate outranks the generic "it just stopped" reason, and that the
    LAST such line wins - the truncated event is what the operator needs, the
    TSX is a red herring that happened first.
    """
    rec = _FIXTURES_DIR / "codex_brace_line_no_terminal.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.error_reason is not None
    assert result.error_reason.startswith("malformed codex JSON line:")
    assert '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input' in (
        result.error_reason
    )
    assert "formatTokens" not in result.error_reason, (
        "the echoed TSX must not be reported as the cause over the truncated event"
    )
    assert MISSING_TERMINAL_TURN_REASON not in result.error_reason
    assert result.num_turns == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_codex_own_failure_reason_outranks_an_echoed_line() -> None:
    """Promotion order, pinned at the top: what codex SAID beats what we guessed.

    Both candidates are live here - an echoed TSX line and a `turn.failed` -
    and neither turn completed. Reporting the TSX would bury the one statement
    of cause the run actually produced (#1116, #1117).
    """
    rec = _FIXTURES_DIR / "codex_turn_failed_after_brace_echo.jsonl"
    collector = _RecordingCollector()
    processor, _tokens = _make_processor(collector)

    result = await processor.process_stream(_lines(rec), _NoopWorkspace())

    assert result.error_reason == "codex reported: stream disconnected before completion"
